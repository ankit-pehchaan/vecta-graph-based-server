"""
Financial Education Pipeline Orchestrator.

Implements the multi-agent pipeline architecture from arch.md:
1. Intent Classifier - Understand what user is trying to communicate
2. Extraction Agent - Pull structured financial data from message
3. Profile State Manager - Merge with existing profile
4. QA/Validator Agent - Check if we have enough information
5. Strategy/Router Agent - Decide conversation direction
6. Conversation Agent (Jamie) - Generate human response
7. Output QA Agent - Review response quality

Each stage has debug logging for observability.
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.core.config import settings
from app.core.prompts import (
    INTENT_CLASSIFIER_PROMPT,
    QA_VALIDATOR_PROMPT,
    STRATEGY_ROUTER_PROMPT,
    OUTPUT_QA_PROMPT,
    FINANCIAL_ADVISER_SYSTEM_PROMPT,
    PROFILE_EXTRACTOR_SYSTEM_PROMPT,
    CONTEXT_ASSESSMENT_PROMPT,
)
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.repositories.user_repository import UserRepository

# Configure logger for pipeline
logger = logging.getLogger("education_pipeline")
logger.setLevel(logging.DEBUG)

# Add console handler if not already present
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


# =============================================================================
# PYDANTIC SCHEMAS FOR STRUCTURED OUTPUTS
# =============================================================================

class LifeContextShared(BaseModel):
    """What life context was shared in this message."""
    persona_info: bool = Field(default=False, description="Did they share age, relationship, job, family, location?")
    life_aspirations: bool = Field(default=False, description="Did they share plans (marriage, kids, career, retirement)?")
    life_context_type: Optional[str] = Field(
        default=None,
        description="Type: age, relationship, family, career, location, marriage_plans, family_planning, career_trajectory, retirement_vision, lifestyle_aspirations"
    )


class InformationShared(BaseModel):
    """What financial information was shared in this message."""
    contains_financial_data: bool = Field(default=False, description="Did they share numbers/financial facts?")
    contains_personal_context: bool = Field(default=False, description="Did they share life context?")
    answer_completeness: str = Field(
        default="complete",
        description="How complete was their answer: complete, partial, vague, evasive"
    )


class EmotionalSignals(BaseModel):
    """Emotional state detected in message."""
    detected_emotion: Optional[str] = Field(
        default=None,
        description="Emotion: anxious, excited, frustrated, overwhelmed, confused, defensive, neutral, or null"
    )
    intensity: str = Field(default="low", description="Intensity: low, medium, high")


class ConversationDynamics(BaseModel):
    """Critical dynamics for strategy decisions."""
    user_engagement: str = Field(
        default="engaged",
        description="Engagement level: engaged, brief, resistant"
    )
    wants_to_go_deeper: bool = Field(
        default=False,
        description="Are they curious to learn more?"
    )
    trying_to_skip_ahead: bool = Field(
        default=False,
        description="Are they jumping to advice before discovery? CRITICAL to detect."
    )


class IntentClassification(BaseModel):
    """Output from Intent Classifier agent - aligned with arch.md."""
    primary_intent: str = Field(
        ...,
        description="Primary intent: sharing_persona, sharing_life_aspirations, sharing_financial, stating_goal, asking_question, expressing_emotion, seeking_validation, pushing_back, small_talk, unclear"
    )
    goals_mentioned: List[str] = Field(
        default_factory=list,
        description="ALL goals mentioned (list) - noted for later, not acted on immediately"
    )
    life_context_shared: LifeContextShared = Field(
        default_factory=LifeContextShared,
        description="What life context was shared in this message"
    )
    information_shared: InformationShared = Field(
        default_factory=InformationShared
    )
    emotional_signals: EmotionalSignals = Field(
        default_factory=EmotionalSignals
    )
    conversation_dynamics: ConversationDynamics = Field(
        default_factory=ConversationDynamics
    )


class ValidationResult(BaseModel):
    """Output from QA/Validator agent - focuses on big picture completeness."""
    discovery_completeness: str = Field(
        default="early",
        description="How complete is our understanding: early (Phase 1 incomplete), partial (Phase 1 done but 2/3 incomplete), substantial (Phases 1-3 mostly complete), comprehensive (Phases 1-4 complete)"
    )
    current_phase: str = Field(
        default="persona",
        description="Which phase we should be in: persona, life_aspirations, financial_foundation, goals_overview, ready_for_depth"
    )
    life_foundation_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about their PERSONA (Phase 1): age, relationship status, kids/family, career, location"
    )
    life_aspirations_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about their LIFE VISION (Phase 2): marriage plans, family planning, career trajectory, lifestyle goals, retirement vision"
    )
    financial_foundation_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about finances (Phase 3): income, savings, debts, super, insurance"
    )
    goals_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about goals (Phase 4): only know one goal, no priorities, no timelines, haven't explored retirement, haven't explored family goals"
    )
    priority_questions: List[str] = Field(
        default_factory=list,
        description="Most important 2-3 things to learn next - MUST follow phase order: Persona → Life Aspirations → Finances → Goals"
    )
    ready_for_goal_planning: bool = Field(
        default=False,
        description="TRUE only when Phases 1-3 complete and we understand multiple goals. FALSE if any phase incomplete."
    )
    contradictions: List[str] = Field(
        default_factory=list,
        description="Conflicting information detected in profile"
    )


class StrategyDecision(BaseModel):
    """Output from Strategy/Router agent - aligned with arch.md."""
    next_action: str = Field(
        ...,
        description="Action: probe_gap, clarify_vague, resolve_contradiction, acknowledge_emotion, redirect_to_discovery, pivot_to_education, reality_check, goal_deep_dive, handle_resistance"
    )
    current_phase: str = Field(
        default="persona",
        description="Current discovery phase: persona, financial_foundation, goals_overview, reality_check, goal_deep_dive"
    )
    action_details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details for the action: target_field, probe_approach, mismatch_detected, education_approach, etc."
    )
    question_intensity: str = Field(
        default="standard",
        description="How aggressive to probe: gentle, standard, direct"
    )
    conversation_tone: str = Field(
        default="warm",
        description="Tone: warm, direct, gentle, encouraging, grounding, reality-check"
    )
    response_length: str = Field(
        default="medium",
        description="Length directive for Jamie: brief (1-3 sentences), medium (3-5), detailed (longer)"
    )
    things_to_avoid: List[str] = Field(
        default_factory=list,
        description="Specific things NOT to do in this response"
    )
    strategic_reasoning: str = Field(
        default="",
        description="Why this is the right move now, which phase we're in"
    )


class OutputQAChecks(BaseModel):
    """Explicit boolean checks for output quality."""
    follows_directive: bool = Field(default=True, description="Does it follow the strategy directive?")
    sounds_human: bool = Field(default=True, description="Does it sound natural, not robotic?")
    appropriate_length: bool = Field(default=True, description="Is length appropriate for directive?")
    no_compliance_issues: bool = Field(default=True, description="No specific advice, proper hedging?")
    emotionally_appropriate: bool = Field(default=True, description="Matches user's emotional state?")
    no_multiple_questions: bool = Field(default=True, description="Only ONE question asked?")
    no_robotic_patterns: bool = Field(default=True, description="No 'Great!', 'help me understand', etc.?")
    no_deflection: bool = Field(default=True, description="Didn't suggest talking to another adviser?")
    no_goal_framing: bool = Field(default=True, description="Doesn't tie questions back to goals (e.g., 'that'll help with the house')")


class OutputQAIssue(BaseModel):
    """A specific issue found in the response."""
    issue_type: str = Field(..., description="Type: robotic_pattern, directive_miss, compliance, tone, length, multiple_questions, deflection, goal_framing")
    issue_description: str = Field(..., description="What's wrong")
    severity: str = Field(default="minor", description="Severity: minor, major, blocking")


class OutputQAResult(BaseModel):
    """Output from Output QA agent - aligned with arch.md."""
    approval: str = Field(
        ...,
        description="Status: approved, needs_revision, blocked"
    )
    checks: OutputQAChecks = Field(
        default_factory=OutputQAChecks
    )
    issues: List[OutputQAIssue] = Field(
        default_factory=list
    )
    revision_guidance: Optional[str] = Field(
        default=None,
        description="If needs_revision, what specifically to fix"
    )
    blocking_reason: Optional[str] = Field(
        default=None,
        description="If blocked, why this can't be sent"
    )


# =============================================================================
# OPTIMIZED COMBINED SCHEMA (for 3-stage pipeline)
# =============================================================================

class ContextAssessment(BaseModel):
    """
    Combined output replacing Intent + Validation + Strategy stages.
    Used by the optimized 3-stage pipeline for lower latency.
    """
    # Intent fields
    primary_intent: str = Field(
        default="sharing_info",
        description="Primary intent: sharing_persona, sharing_life_aspirations, sharing_financial, stating_goal, asking_question, expressing_emotion, pushing_back, small_talk, unclear"
    )
    goals_mentioned: List[str] = Field(
        default_factory=list,
        description="ALL goals mentioned - noted for later, not acted on immediately"
    )
    user_engagement: str = Field(
        default="engaged",
        description="Engagement level: engaged, brief, resistant"
    )
    trying_to_skip_ahead: bool = Field(
        default=False,
        description="Are they jumping to advice before discovery?"
    )
    detected_emotion: Optional[str] = Field(
        default=None,
        description="Emotion: anxious, excited, frustrated, overwhelmed, confused, defensive, neutral"
    )

    # Validation fields
    current_phase: str = Field(
        default="persona",
        description="Which phase: persona, life_aspirations, financial_foundation, goals_overview, ready_for_depth"
    )
    discovery_completeness: str = Field(
        default="early",
        description="How complete: early, partial, substantial, comprehensive"
    )
    priority_gaps: List[str] = Field(
        default_factory=list,
        description="Most important gaps to fill next (2-3 items)"
    )
    ready_for_goal_planning: bool = Field(
        default=False,
        description="TRUE only when Phases 1-3 complete"
    )

    # Strategy fields
    next_action: str = Field(
        default="probe_gap",
        description="Action: probe_gap, clarify_vague, acknowledge_emotion, redirect_to_discovery, pivot_to_education, handle_resistance"
    )
    target_field: Optional[str] = Field(
        default=None,
        description="Which field to probe: age, relationship_status, kids_family, career, marriage_plans, family_planning, career_trajectory, retirement_vision, income, etc."
    )
    conversation_tone: str = Field(
        default="warm",
        description="Tone: warm, direct, gentle, encouraging, grounding"
    )
    response_length: str = Field(
        default="medium",
        description="Length: brief (1-3 sentences), medium (3-5), detailed"
    )
    things_to_avoid: List[str] = Field(
        default_factory=list,
        description="Things NOT to do in this response"
    )

    def model_post_init(self, __context) -> None:
        """Automatically add 'no goal references' during discovery phases."""
        discovery_phases = ("persona", "life_aspirations", "financial_foundation")
        if self.current_phase in discovery_phases:
            no_goal_ref = "Don't reference the goal in questions or comments"
            if no_goal_ref not in self.things_to_avoid:
                self.things_to_avoid.append(no_goal_ref)


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class EducationPipeline:
    """
    Multi-agent pipeline for financial education conversations.

    Orchestrates specialized agents in sequence, with each stage
    adding context and decisions for the next stage.

    Model Configuration:
    - FAST_MODEL: Used for classification, validation, strategy (lower latency)
    - QUALITY_MODEL: Used for response generation (higher quality)

    The fast model handles structured output tasks where speed matters.
    The quality model handles the final response where quality matters.
    """

    # Model configuration - can be overridden
    FAST_MODEL = "gpt-4o-mini"      # For intent, validation, strategy, QA
    QUALITY_MODEL = "gpt-4o"        # For response generation (Jamie)

    def __init__(self, db_manager, use_fast_models: bool = True):
        """
        Initialize the pipeline.

        Args:
            db_manager: Database manager for profile storage
            use_fast_models: If True, use gpt-4o-mini for classification stages (faster)
                           If False, use gpt-4o for all stages (higher quality but slower)
        """
        self.db_manager = db_manager
        self._agents: Dict[str, Agent] = {}
        self._db_dir = "tmp/agents"
        self._use_fast_models = use_fast_models
        os.makedirs(self._db_dir, exist_ok=True)

        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

        model_mode = "FAST (gpt-4o-mini for stages 1-4,6)" if use_fast_models else "QUALITY (gpt-4o for all)"
        logger.info(f"EducationPipeline initialized - Model Mode: {model_mode}")

    # -------------------------------------------------------------------------
    # AGENT FACTORY METHODS
    # -------------------------------------------------------------------------

    def _get_model_id(self, for_response: bool = False) -> str:
        """Get the appropriate model ID based on configuration."""
        if for_response:
            return self.QUALITY_MODEL  # Always use quality model for responses
        return self.FAST_MODEL if self._use_fast_models else self.QUALITY_MODEL

    def _get_intent_classifier(self, username: str) -> Agent:
        """Get or create Intent Classifier agent (uses fast model)."""
        key = f"intent_{username}_{self._use_fast_models}"
        if key not in self._agents:
            model_id = self._get_model_id(for_response=False)
            self._agents[key] = Agent(
                name="Intent Classifier",
                model=OpenAIChat(id=model_id),
                instructions=INTENT_CLASSIFIER_PROMPT,
                output_schema=IntentClassification,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Intent Classifier agent for {username} (model: {model_id})")
        return self._agents[key]

    def _get_qa_validator(self, username: str) -> Agent:
        """Get or create QA/Validator agent (uses fast model)."""
        key = f"qa_{username}_{self._use_fast_models}"
        if key not in self._agents:
            model_id = self._get_model_id(for_response=False)
            self._agents[key] = Agent(
                name="QA Validator",
                model=OpenAIChat(id=model_id),
                instructions=QA_VALIDATOR_PROMPT,
                output_schema=ValidationResult,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created QA Validator agent for {username} (model: {model_id})")
        return self._agents[key]

    def _get_strategy_router(self, username: str) -> Agent:
        """Get or create Strategy/Router agent (uses fast model)."""
        key = f"strategy_{username}_{self._use_fast_models}"
        if key not in self._agents:
            model_id = self._get_model_id(for_response=False)
            self._agents[key] = Agent(
                name="Strategy Router",
                model=OpenAIChat(id=model_id),
                instructions=STRATEGY_ROUTER_PROMPT,
                output_schema=StrategyDecision,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Strategy Router agent for {username} (model: {model_id})")
        return self._agents[key]

    def _get_conversation_agent(self, username: str, user_name: Optional[str] = None) -> Agent:
        """Get or create Conversation Agent (Jamie) - ALWAYS uses quality model."""
        key = f"jamie_{username}"
        if key not in self._agents:
            db_file = os.path.join(self._db_dir, f"jamie_{username}.db")
            instructions = FINANCIAL_ADVISER_SYSTEM_PROMPT
            if user_name:
                instructions += f"\n\nYou're speaking with {user_name}."

            # Jamie ALWAYS uses the quality model for best responses
            self._agents[key] = Agent(
                name="Jamie (Financial Educator)",
                model=OpenAIChat(id=self.QUALITY_MODEL),
                instructions=instructions,
                db=SqliteDb(db_file=db_file),
                user_id=username,
                add_history_to_context=True,
                num_history_runs=10,
                markdown=True,
                debug_mode=False
            )
            logger.debug(f"Created Conversation Agent (Jamie) for {username} (model: {self.QUALITY_MODEL})")
        return self._agents[key]

    def _get_output_qa(self, username: str) -> Agent:
        """Get or create Output QA agent (uses fast model)."""
        key = f"output_qa_{username}_{self._use_fast_models}"
        if key not in self._agents:
            model_id = self._get_model_id(for_response=False)
            self._agents[key] = Agent(
                name="Output QA",
                model=OpenAIChat(id=model_id),
                instructions=OUTPUT_QA_PROMPT,
                output_schema=OutputQAResult,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Output QA agent for {username} (model: {model_id})")
        return self._agents[key]

    def _get_context_assessor(self, username: str) -> Agent:
        """Get or create Context Assessment agent (combined intent+validation+strategy)."""
        key = f"context_assessor_{username}"
        if key not in self._agents:
            self._agents[key] = Agent(
                name="Context Assessor",
                model=OpenAIChat(id=self.FAST_MODEL),  # Always use fast model
                instructions=CONTEXT_ASSESSMENT_PROMPT,
                output_schema=ContextAssessment,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Context Assessor agent for {username} (model: {self.FAST_MODEL})")
        return self._agents[key]

    # -------------------------------------------------------------------------
    # PIPELINE STAGES
    # -------------------------------------------------------------------------

    async def _stage_1_classify_intent(
        self,
        username: str,
        user_message: str
    ) -> IntentClassification:
        """
        Stage 1: Intent Classification

        Understand what the user is trying to do/say.
        """
        logger.info("=" * 60)
        logger.info("STAGE 1: INTENT CLASSIFICATION")
        logger.info(f"User message: {user_message[:100]}{'...' if len(user_message) > 100 else ''}")

        agent = self._get_intent_classifier(username)

        prompt = f"""Analyze this message from a user seeking financial education:

MESSAGE: {user_message}

Classify the intent, emotional state, urgency, and key topics."""

        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(response, 'content') and isinstance(response.content, IntentClassification):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = IntentClassification(**response.content)
            else:
                # Fallback to default
                result = IntentClassification(
                    primary_intent="unclear"
                )

            logger.info(f"Primary Intent: {result.primary_intent}")
            logger.info(f"Goals Mentioned: {', '.join(result.goals_mentioned) if result.goals_mentioned else 'None'}")

            # Life context shared
            life_ctx = result.life_context_shared
            if life_ctx.persona_info:
                logger.info("Contains Persona Info: Yes")
            if life_ctx.life_aspirations:
                logger.info("Contains Life Aspirations: Yes")
            if life_ctx.life_context_type:
                logger.info(f"Life Context Type: {life_ctx.life_context_type}")

            # Information shared
            info = result.information_shared
            logger.info(f"Answer Completeness: {info.answer_completeness}")
            if info.contains_financial_data:
                logger.info("Contains Financial Data: Yes")
            if info.contains_personal_context:
                logger.info("Contains Personal Context: Yes")

            # Emotional signals
            emo = result.emotional_signals
            if emo.detected_emotion:
                logger.info(f"Emotion Detected: {emo.detected_emotion} (intensity: {emo.intensity})")

            # Conversation dynamics - CRITICAL
            dynamics = result.conversation_dynamics
            logger.info(f"User Engagement: {dynamics.user_engagement}")
            if dynamics.trying_to_skip_ahead:
                logger.warning("TRYING TO SKIP AHEAD: Yes - need to redirect to discovery")
            if dynamics.user_engagement == "resistant":
                logger.warning("USER RESISTANT: Yes - handle carefully")

            return result

        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return IntentClassification(
                primary_intent="unclear"
            )

    async def _stage_2_extract_data(
        self,
        username: str,
        user_message: str,
        existing_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Stage 2: Data Extraction

        Pull structured financial data from the message.
        Uses existing profile extractor logic.
        """
        logger.info("=" * 60)
        logger.info("STAGE 2: DATA EXTRACTION")
        logger.info(f"Extracting from message: {user_message[:100]}{'...' if len(user_message) > 100 else ''}")

        # Import profile extractor here to avoid circular imports
        from app.services.profile_extractor import ProfileExtractor

        extractor = ProfileExtractor(self.db_manager)

        try:
            result = await extractor.extract_and_update_profile(username, user_message)

            if result:
                changes = result.get("changes", {})
                logger.info(f"Extracted data:")
                for key, value in changes.items():
                    if isinstance(value, list):
                        logger.info(f"  - {key}: {len(value)} item(s)")
                    else:
                        logger.info(f"  - {key}: {value}")
                return result
            else:
                logger.info("No new data extracted from message")
                return {}

        except Exception as e:
            logger.error(f"Data extraction failed: {e}")
            return {}

    async def _stage_3_validate_profile(
        self,
        username: str,
        intent: IntentClassification,
        profile: Dict[str, Any]
    ) -> ValidationResult:
        """
        Stage 3: QA/Validation

        Check if we have sufficient information for the current intent.
        """
        logger.info("=" * 60)
        logger.info("STAGE 3: QA/VALIDATION")
        logger.info(f"Validating profile for intent: {intent.primary_intent}")

        agent = self._get_qa_validator(username)

        # Format profile summary
        profile_summary = self._format_profile_summary(profile)

        # Determine engagement level for context
        engagement = intent.conversation_dynamics.user_engagement if intent.conversation_dynamics else "engaged"

        prompt = f"""Evaluate how complete our understanding of this user is - for their WHOLE LIFE, not just one goal.

USER INTENT: {intent.primary_intent}
GOALS MENTIONED SO FAR: {', '.join(intent.goals_mentioned) if intent.goals_mentioned else 'None yet'}
USER ENGAGEMENT: {engagement}

CURRENT PROFILE:
{profile_summary}

Remember: PERSON → LIFE VISION → FINANCES → ALL GOALS → ADVICE

Check against the PHASED checklist (in order):

PHASE 1 - PERSONA (Who are they?):
- Age (CRITICAL - shapes everything)
- Relationship status (solo, partnered, married, divorced)
- Family (kids? how many? planning kids?)
- Career/job situation
- Location

PHASE 2 - LIFE ASPIRATIONS (What kind of life do they want?):
- Marriage plans (if partnered)
- Family planning (want kids? more kids? when?)
- Career trajectory (where in 5-10 years?)
- Lifestyle aspirations (sea change? upgrade? simplify?)
- Retirement vision (when? what does it look like?)

PHASE 3 - FINANCIAL FOUNDATION (What do they have?):
- Income, savings, debts, super, insurance

PHASE 4 - ALL GOALS (What do they want?):
- Not just the first goal mentioned - what else matters?
- Retirement, education, travel, lifestyle goals?

Determine:
1. Which phase are we currently in? (persona/life_aspirations/financial_foundation/goals_overview/ready_for_depth)
2. How complete is our understanding? (early/partial/substantial/comprehensive)
3. What persona gaps exist (Phase 1)?
4. What life aspiration gaps exist (Phase 2)?
5. What financial foundation gaps exist (Phase 3)?
6. What goals gaps exist (Phase 4)?
7. Priority questions - MUST follow phase order!
8. Are we ready for goal planning? (ONLY if Phases 1-3 complete)"""

        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(response, 'content') and isinstance(response.content, ValidationResult):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = ValidationResult(**response.content)
            else:
                result = ValidationResult(
                    discovery_completeness="early",
                    ready_for_goal_planning=False
                )

            logger.info(f"Discovery Completeness: {result.discovery_completeness}")
            logger.info(f"Current Phase: {result.current_phase}")
            logger.info(f"Ready for Goal Planning: {result.ready_for_goal_planning}")
            if result.life_foundation_gaps:
                logger.info(f"Persona Gaps (Phase 1): {', '.join(result.life_foundation_gaps)}")
            if result.life_aspirations_gaps:
                logger.info(f"Life Aspirations Gaps (Phase 2): {', '.join(result.life_aspirations_gaps)}")
            if result.financial_foundation_gaps:
                logger.info(f"Financial Gaps (Phase 3): {', '.join(result.financial_foundation_gaps)}")
            if result.goals_gaps:
                logger.info(f"Goals Gaps (Phase 4): {', '.join(result.goals_gaps)}")
            if result.priority_questions:
                logger.info(f"Priority Questions: {len(result.priority_questions)} - {result.priority_questions[0] if result.priority_questions else ''}")
            if result.contradictions:
                logger.warning(f"Contradictions Found: {', '.join(result.contradictions)}")

            return result

        except Exception as e:
            logger.error(f"Profile validation failed: {e}")
            return ValidationResult(
                discovery_completeness="early",
                ready_for_goal_planning=False
            )

    async def _stage_4_decide_strategy(
        self,
        username: str,
        intent: IntentClassification,
        validation: ValidationResult,
        profile: Dict[str, Any]
    ) -> StrategyDecision:
        """
        Stage 4: Strategy/Routing

        Decide what should happen next in the conversation.
        """
        logger.info("=" * 60)
        logger.info("STAGE 4: STRATEGY/ROUTING")
        logger.info(f"Deciding strategy for intent: {intent.primary_intent}, discovery: {validation.discovery_completeness}")

        agent = self._get_strategy_router(username)

        # Extract emotional state from nested structure
        emotional_state = intent.emotional_signals.detected_emotion if intent.emotional_signals and intent.emotional_signals.detected_emotion else "neutral"
        emotional_intensity = intent.emotional_signals.intensity if intent.emotional_signals else "low"

        # Extract conversation dynamics
        dynamics = intent.conversation_dynamics
        user_engagement = dynamics.user_engagement if dynamics else "engaged"
        trying_to_skip = dynamics.trying_to_skip_ahead if dynamics else False
        answer_completeness = intent.information_shared.answer_completeness if intent.information_shared else "complete"

        # Get life aspirations gaps (new field)
        life_aspirations_gaps = getattr(validation, 'life_aspirations_gaps', [])
        current_phase = getattr(validation, 'current_phase', 'persona')

        prompt = f"""Decide the conversation strategy - with STRONG bias toward understanding the PERSON first.

CARDINAL RULE: A mentioned goal is an INVITATION to understand the person, NOT permission to discuss that goal.

USER INTENT: {intent.primary_intent}
EMOTIONAL STATE: {emotional_state} (intensity: {emotional_intensity})
GOALS MENTIONED: {', '.join(intent.goals_mentioned) if intent.goals_mentioned else 'None yet'}

CONVERSATION DYNAMICS:
- User Engagement: {user_engagement}
- Answer Completeness: {answer_completeness}
- Trying to Skip Ahead: {trying_to_skip}

VALIDATION RESULTS:
- Current Phase: {current_phase}
- Discovery Completeness: {validation.discovery_completeness}
- Ready for Goal Planning: {validation.ready_for_goal_planning}
- Persona Gaps (Phase 1): {', '.join(validation.life_foundation_gaps) if validation.life_foundation_gaps else 'None'}
- Life Aspirations Gaps (Phase 2): {', '.join(life_aspirations_gaps) if life_aspirations_gaps else 'None'}
- Financial Gaps (Phase 3): {', '.join(validation.financial_foundation_gaps) if validation.financial_foundation_gaps else 'None'}
- Goals Gaps (Phase 4): {', '.join(validation.goals_gaps) if validation.goals_gaps else 'None'}
- Priority Questions: {validation.priority_questions}

PHASE ORDER (SACRED - NO EXCEPTIONS):
Persona → Life Aspirations → Financial Foundation → All Goals → Reality Check → Deep Dive

CRITICAL RULES:
- AGE IS ALWAYS THE FIRST QUESTION after a goal is stated. Not household, not income. AGE.
- If age unknown → target_field MUST be "age"
- If Phase 1 (Persona) incomplete → MUST stay in persona phase
- If Phase 2 (Life Aspirations) incomplete → CANNOT discuss finances deeply yet
- If user stated a goal → acknowledge warmly, then ask AGE immediately
- If only one goal mentioned → MUST explore other goals before diving in

QUESTION ORDER IN PHASE 1:
1. Age (FIRST - mandatory)
2. Relationship status (AFTER age)
3. Family/kids (AFTER relationship)
4. Career (AFTER family)
5. Location (AFTER career)

Return a StrategyDecision with:
1. current_phase: persona | life_aspirations | financial_foundation | goals_overview | reality_check | goal_deep_dive
2. next_action: probe_gap | clarify_vague | acknowledge_emotion | redirect_to_discovery | pivot_to_education | handle_resistance
3. action_details: target_field (use new fields like marriage_plans, family_planning, career_trajectory, retirement_vision), probe_approach, educational_hook
4. conversation_tone: warm | direct | gentle | encouraging | grounding
5. response_length: brief | medium | detailed
6. things_to_avoid: list of things NOT to do
7. strategic_reasoning: why this is the right move and which phase we're in"""

        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(response, 'content') and isinstance(response.content, StrategyDecision):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = StrategyDecision(**response.content)
            else:
                result = StrategyDecision(
                    next_action="probe_gap",
                    action_details={"target_field": "household_status", "probe_approach": "contextual"},
                    conversation_tone="warm",
                    response_length="medium"
                )

            logger.info(f"Current Phase: {result.current_phase}")
            logger.info(f"Next Action: {result.next_action}")
            logger.info(f"Question Intensity: {result.question_intensity}")
            logger.info(f"Conversation Tone: {result.conversation_tone}")
            logger.info(f"Response Length: {result.response_length}")
            if result.action_details:
                logger.info(f"Action Details: {result.action_details}")
            if result.things_to_avoid:
                logger.warning(f"Things to Avoid: {', '.join(result.things_to_avoid[:3])}")
            if result.strategic_reasoning:
                logger.debug(f"Strategic Reasoning: {result.strategic_reasoning[:100]}")

            return result

        except Exception as e:
            logger.error(f"Strategy decision failed: {e}")
            return StrategyDecision(
                next_action="probe_gap",
                action_details={"target_field": "household_status"},
                conversation_tone="warm",
                response_length="medium"
            )

    async def _stage_5_generate_response(
        self,
        username: str,
        user_message: str,
        strategy: StrategyDecision,
        intent: IntentClassification,
        profile: Dict[str, Any]
    ) -> str:
        """
        Stage 5: Response Generation (Jamie)

        Generate natural, human response following the strategy.
        """
        logger.info("=" * 60)
        logger.info("STAGE 5: RESPONSE GENERATION (Jamie)")
        logger.info(f"Generating response with strategy: {strategy.next_action}")

        # Get user's actual name for personalization
        user_name = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)
            if user:
                user_name = user.get("name")

        agent = self._get_conversation_agent(username, user_name)

        # Build context for Jamie - using new schema fields
        context_parts = []

        context_parts.append(f"[STRATEGY DIRECTIVE - DO NOT MENTION THIS TO USER]")
        context_parts.append(f"CRITICAL: Ask only ONE question. Not two, not three. ONE.")
        context_parts.append(f"Action: {strategy.next_action}")
        context_parts.append(f"Tone: {strategy.conversation_tone}")
        context_parts.append(f"Response Length: {strategy.response_length}")

        # Add action details if present
        if strategy.action_details:
            target_field = strategy.action_details.get("target_field", "")
            probe_approach = strategy.action_details.get("probe_approach", "")
            if target_field:
                context_parts.append(f"Focus Area: {target_field}")
            if probe_approach:
                context_parts.append(f"Probe Approach: {probe_approach}")
            framing_hint = strategy.action_details.get("framing_hint", "")
            if framing_hint:
                context_parts.append(f"Framing: {framing_hint}")

        # Things to avoid
        if strategy.things_to_avoid:
            context_parts.append(f"AVOID: {', '.join(strategy.things_to_avoid)}")

        # Emotional context from intent
        emotional_state = intent.emotional_signals.detected_emotion if intent.emotional_signals and intent.emotional_signals.detected_emotion else None
        if emotional_state and emotional_state != "neutral":
            intensity = intent.emotional_signals.intensity if intent.emotional_signals else "low"
            context_parts.append(f"User seems {emotional_state} ({intensity}) - acknowledge appropriately")

        if intent.goals_mentioned:
            context_parts.append(f"Goals mentioned so far: {', '.join(intent.goals_mentioned)} - explore other goals too, don't just focus on these")

        context_parts.append(f"REMINDER: ONE question only. If you write 'And...' to add a second question, delete it.")
        context_parts.append(f"[END DIRECTIVE]")
        context_parts.append(f"")
        context_parts.append(f"User: {user_message}")

        full_prompt = "\n".join(context_parts)

        try:
            response = await agent.arun(full_prompt) if hasattr(agent, 'arun') else agent.run(full_prompt)

            result = response.content if hasattr(response, 'content') else str(response)

            logger.info(f"Generated Response Length: {len(result)} chars")
            logger.debug(f"Response Preview: {result[:200]}...")

            return result

        except Exception as e:
            logger.error(f"Response generation failed: {e}")
            return "I apologize, but I'm having trouble processing that right now. Could you try rephrasing?"

    async def _stage_6_review_output(
        self,
        username: str,
        user_message: str,
        response: str,
        strategy: StrategyDecision
    ) -> Tuple[str, OutputQAResult]:
        """
        Stage 6: Output QA

        Review the response for quality, compliance, and strategy alignment.
        """
        logger.info("=" * 60)
        logger.info("STAGE 6: OUTPUT QA")
        logger.info(f"Reviewing response quality and compliance")

        agent = self._get_output_qa(username)

        # Build action details string for context
        action_details_str = ""
        if strategy.action_details:
            target = strategy.action_details.get("target_field", "")
            approach = strategy.action_details.get("probe_approach", "")
            if target:
                action_details_str += f"Target: {target}. "
            if approach:
                action_details_str += f"Approach: {approach}. "

        prompt = f"""Review this financial education response for quality and compliance.

USER MESSAGE: {user_message}

STRATEGY DIRECTIVE:
- Action: {strategy.next_action}
- Tone: {strategy.conversation_tone}
- Response Length: {strategy.response_length}
- Action Details: {action_details_str if action_details_str else 'None specified'}
- Things to Avoid: {', '.join(strategy.things_to_avoid) if strategy.things_to_avoid else 'None specified'}

GENERATED RESPONSE:
{response}

Evaluate against the OUTPUT QA checks:
1. follows_directive - Does it follow the strategy action?
2. sounds_human - Natural language, not robotic?
3. appropriate_length - Matches the length directive ({strategy.response_length})?
4. no_compliance_issues - No specific financial advice?
5. emotionally_appropriate - Right tone for user's state?
6. no_multiple_questions - Only ONE question asked? (CRITICAL)
7. no_robotic_patterns - No "Great!", "help me understand", etc.?
8. no_deflection - Didn't suggest talking to another adviser?

Return structured approval with explicit boolean checks."""

        try:
            qa_response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(qa_response, 'content') and isinstance(qa_response.content, OutputQAResult):
                result = qa_response.content
            elif hasattr(qa_response, 'content') and isinstance(qa_response.content, dict):
                result = OutputQAResult(**qa_response.content)
            else:
                result = OutputQAResult(
                    approval="approved"
                )

            # Log using new schema fields
            logger.info(f"Approval: {result.approval}")

            # Log explicit checks
            if result.checks:
                checks = result.checks
                failed_checks = []
                if not checks.follows_directive:
                    failed_checks.append("follows_directive")
                if not checks.sounds_human:
                    failed_checks.append("sounds_human")
                if not checks.appropriate_length:
                    failed_checks.append("appropriate_length")
                if not checks.no_compliance_issues:
                    failed_checks.append("compliance")
                if not checks.emotionally_appropriate:
                    failed_checks.append("emotionally_appropriate")
                if not checks.no_multiple_questions:
                    failed_checks.append("multiple_questions")
                if not checks.no_robotic_patterns:
                    failed_checks.append("robotic_patterns")
                if not checks.no_deflection:
                    failed_checks.append("deflection")

                if failed_checks:
                    logger.warning(f"Failed Checks: {', '.join(failed_checks)}")
                else:
                    logger.info("All checks passed")

            # Log issues with severity
            if result.issues:
                for issue in result.issues:
                    if issue.severity == "blocking":
                        logger.error(f"BLOCKING Issue: [{issue.issue_type}] {issue.issue_description}")
                    elif issue.severity == "major":
                        logger.warning(f"Major Issue: [{issue.issue_type}] {issue.issue_description}")
                    else:
                        logger.info(f"Minor Issue: [{issue.issue_type}] {issue.issue_description}")

            if result.revision_guidance:
                logger.info(f"Revision Guidance: {result.revision_guidance[:100]}")

            # If blocked, log the reason
            if result.approval == "blocked":
                logger.error(f"Response BLOCKED: {result.blocking_reason}")
            elif result.approval == "needs_revision":
                logger.warning("Response needs revision - returning anyway")

            return response, result

        except Exception as e:
            logger.error(f"Output QA failed: {e}")
            return response, OutputQAResult(
                approval="approved"
            )

    # -------------------------------------------------------------------------
    # MAIN PIPELINE ENTRY POINT
    # -------------------------------------------------------------------------

    async def process_message(
        self,
        username: str,
        user_message: str,
        skip_output_qa: bool = False
    ) -> Dict[str, Any]:
        """
        Process a user message through the full education pipeline.

        Optimized for latency with parallel execution where possible:
        - Stage 1 (Intent) and Stage 2 (Extraction) run in PARALLEL
        - Stage 6 (Output QA) can be skipped for faster responses

        Args:
            username: The user's identifier
            user_message: The message to process
            skip_output_qa: If True, skip Stage 6 for faster response (default False)

        Returns:
            Dictionary containing:
            - response: The generated response text
            - intent: Intent classification result
            - validation: Validation result
            - strategy: Strategy decision
            - qa_result: Output QA result (None if skipped)
            - extracted_data: Any data extracted from message
            - duration_seconds: Total processing time
        """
        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE START (Parallel Optimized)")
        logger.info(f"User: {username}")
        logger.info(f"Message: {user_message}")
        logger.info(f"Skip Output QA: {skip_output_qa}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Get existing profile
        profile = {}
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username) or {}

        # =====================================================================
        # PARALLEL EXECUTION: Stage 1 (Intent) + Stage 2 (Extraction)
        # Both only need user_message and profile, no interdependency
        # =====================================================================
        parallel_start = datetime.now(timezone.utc)

        intent_task = asyncio.create_task(
            self._stage_1_classify_intent(username, user_message)
        )
        extraction_task = asyncio.create_task(
            self._stage_2_extract_data(username, user_message, profile)
        )

        # Wait for both to complete
        intent, extracted_data = await asyncio.gather(intent_task, extraction_task)

        parallel_duration = (datetime.now(timezone.utc) - parallel_start).total_seconds()
        logger.info(f"Parallel Stage 1+2 Duration: {parallel_duration:.2f}s")

        # Refresh profile after extraction (if data was extracted)
        if extracted_data:
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_username(username) or {}

        # =====================================================================
        # SEQUENTIAL EXECUTION: Stages 3-5 (have dependencies)
        # =====================================================================

        # Stage 3: QA/Validation (needs intent)
        validation = await self._stage_3_validate_profile(username, intent, profile)

        # Stage 4: Strategy/Routing (needs intent + validation)
        strategy = await self._stage_4_decide_strategy(username, intent, validation, profile)

        # Stage 5: Response Generation (needs strategy)
        response = await self._stage_5_generate_response(
            username, user_message, strategy, intent, profile
        )

        # =====================================================================
        # OPTIONAL: Stage 6 (Output QA) - can be skipped for lower latency
        # =====================================================================
        qa_result = None
        if not skip_output_qa:
            final_response, qa_result = await self._stage_6_review_output(
                username, user_message, response, strategy
            )
        else:
            final_response = response
            logger.info("Stage 6 (Output QA) SKIPPED for lower latency")

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE COMPLETE")
        logger.info(f"Total Duration: {duration:.2f}s")
        logger.info("=" * 60)

        return {
            "response": final_response,
            "intent": intent.model_dump(),
            "validation": validation.model_dump(),
            "strategy": strategy.model_dump(),
            "qa_result": qa_result.model_dump() if qa_result else None,
            "extracted_data": extracted_data,
            "duration_seconds": duration
        }

    async def process_message_fast(
        self,
        username: str,
        user_message: str
    ) -> Dict[str, Any]:
        """
        Fast-mode pipeline with minimal latency.

        Optimizations:
        - Runs Stage 1 + 2 in parallel
        - Combines Stage 3 + 4 (validation + strategy) into single LLM call
        - Skips Stage 6 (Output QA)

        Best for: Real-time chat where latency matters more than perfect QA.
        """
        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE START (FAST MODE)")
        logger.info(f"User: {username}")
        logger.info(f"Message: {user_message}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Get existing profile
        profile = {}
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username) or {}

        # PARALLEL: Stage 1 + Stage 2
        intent_task = asyncio.create_task(
            self._stage_1_classify_intent(username, user_message)
        )
        extraction_task = asyncio.create_task(
            self._stage_2_extract_data(username, user_message, profile)
        )

        intent, extracted_data = await asyncio.gather(intent_task, extraction_task)

        # Refresh profile if needed
        if extracted_data:
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_username(username) or {}

        # COMBINED: Stage 3 + 4 (validation + strategy in parallel-ish)
        # We still need to run them sequentially due to dependency,
        # but we skip detailed logging for speed
        validation = await self._stage_3_validate_profile(username, intent, profile)
        strategy = await self._stage_4_decide_strategy(username, intent, validation, profile)

        # Stage 5: Response Generation
        response = await self._stage_5_generate_response(
            username, user_message, strategy, intent, profile
        )

        # SKIP Stage 6 for speed

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE COMPLETE (FAST MODE)")
        logger.info(f"Total Duration: {duration:.2f}s")
        logger.info("=" * 60)

        return {
            "response": response,
            "intent": intent.model_dump(),
            "validation": validation.model_dump(),
            "strategy": strategy.model_dump(),
            "qa_result": None,
            "extracted_data": extracted_data,
            "duration_seconds": duration
        }

    async def process_message_optimized(
        self,
        username: str,
        user_message: str,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Optimized 3-stage pipeline for lowest latency.

        Architecture:
        - Stage 1: Context Assessment (combined intent + validation + strategy) - gpt-4o-mini
        - Stage 2: Data Extraction (parallel with Stage 1) - gpt-4o-mini
        - Stage 3: Response Generation (Jamie) - gpt-4o

        Optimizations:
        - Combines 3 LLM calls into 1 (intent + validation + strategy → context assessment)
        - Runs context assessment + extraction in parallel
        - No Output QA (can be run in background separately)
        - User name passed in to avoid DB lookup

        Expected latency: ~4-5s (down from 10-15s)
        """
        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE START (OPTIMIZED 3-STAGE)")
        logger.info(f"User: {username}")
        logger.info(f"Message: {user_message}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Get existing profile
        profile = {}
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username) or {}

        # =====================================================================
        # PARALLEL: Stage 1 (Context Assessment) + Stage 2 (Extraction)
        # =====================================================================
        parallel_start = datetime.now(timezone.utc)

        assessment_task = asyncio.create_task(
            self._assess_context(username, user_message, profile)
        )
        extraction_task = asyncio.create_task(
            self._stage_2_extract_data(username, user_message, profile)
        )

        assessment, extracted_data = await asyncio.gather(assessment_task, extraction_task)

        parallel_duration = (datetime.now(timezone.utc) - parallel_start).total_seconds()
        logger.info(f"Parallel Assessment+Extraction Duration: {parallel_duration:.2f}s")

        # Refresh profile if extraction updated it
        if extracted_data:
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_username(username) or {}

        # =====================================================================
        # Stage 3: Response Generation (Jamie)
        # =====================================================================
        response = await self._generate_response_from_assessment(
            username, user_message, assessment, profile, user_name
        )

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE COMPLETE (OPTIMIZED 3-STAGE)")
        logger.info(f"Total Duration: {duration:.2f}s")
        logger.info("=" * 60)

        return {
            "response": response,
            "assessment": assessment.model_dump(),
            "extracted_data": extracted_data,
            "duration_seconds": duration
        }

    async def _assess_context(
        self,
        username: str,
        user_message: str,
        profile: Dict[str, Any]
    ) -> ContextAssessment:
        """
        Combined context assessment (replaces intent + validation + strategy).
        Single LLM call that outputs all three components.
        """
        logger.info("-" * 40)
        logger.info("CONTEXT ASSESSMENT")
        logger.info("-" * 40)

        agent = self._get_context_assessor(username)
        profile_summary = self._format_profile_summary(profile)

        # Check what persona fields are missing for enforcement
        age_known = profile.get('age') is not None
        relationship_known = profile.get('relationship_status') is not None
        career_known = profile.get('career') is not None

        prompt = f"""Assess this user message and determine intent, validation status, and strategy.

USER MESSAGE: {user_message}

CURRENT PROFILE:
{profile_summary}

GOALS MENTIONED SO FAR: {', '.join(g.get('description', 'Unknown') for g in profile.get('goals', [])) if profile.get('goals') else 'None yet'}

CRITICAL RULES:
1. AGE MUST BE FIRST: If age is unknown → target_field = "age", current_phase = "persona"
2. PERSONA BEFORE FINANCES: Don't ask about income/savings/debts until we know age, relationship, career
3. Phase order: Persona (age, relationship, career) → Life Aspirations → Finances → Goals
4. One question per response

WHAT WE KNOW:
- Age: {"KNOWN" if age_known else "UNKNOWN - MUST ASK THIS FIRST"}
- Relationship: {"KNOWN" if relationship_known else "UNKNOWN"}
- Career: {"KNOWN" if career_known else "UNKNOWN"}

If age is UNKNOWN, your output MUST have:
- current_phase = "persona"
- target_field = "age"
- next_action = "probe_gap"

Provide your complete assessment."""

        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(response, 'content') and response.content:
                result = response.content
            elif hasattr(response, 'parsed') and response.parsed:
                result = response.parsed
            else:
                result = ContextAssessment()

            if isinstance(result, ContextAssessment):
                # HARD ENFORCEMENT: Persona must be complete before financial questions
                result = self._enforce_persona_first(result, profile)

                logger.info(f"Intent: {result.primary_intent}")
                logger.info(f"Phase: {result.current_phase}")
                logger.info(f"Action: {result.next_action} → {result.target_field}")
                logger.info(f"Completeness: {result.discovery_completeness}")
                return result
            else:
                logger.warning("Context assessment returned unexpected type, using defaults")
                return ContextAssessment()

        except Exception as e:
            logger.error(f"Context assessment error: {e}")
            return ContextAssessment()

    def _enforce_persona_first(
        self,
        assessment: ContextAssessment,
        profile: Dict[str, Any]
    ) -> ContextAssessment:
        """
        HARD ENFORCEMENT: Complete discovery before goal-specific questions.

        Order:
        1. Persona: Age → Relationship → Career
        2. Life Aspirations: Marriage/Family plans
        3. Financial Foundation: Income → Savings → Debts
        4. Other Goals: Ask about other financial goals
        5. ONLY THEN: Goal-specific discussion

        This overrides any LLM decision that tries to skip phases.
        """
        # ===== PERSONA PHASE =====
        age_known = profile.get('age') is not None
        relationship_known = profile.get('relationship_status') is not None
        career_known = profile.get('career') is not None
        persona_complete = age_known and relationship_known and career_known

        # ===== LIFE ASPIRATIONS PHASE =====
        marriage_known = profile.get('marriage_plans') is not None
        family_known = profile.get('family_plans') is not None or profile.get('has_kids') is not None
        life_aspirations_complete = marriage_known or family_known

        # ===== FINANCIAL FOUNDATION PHASE =====
        income_known = profile.get('income') is not None or profile.get('monthly_income') is not None
        # For savings, check if we have any assets recorded
        assets = profile.get('assets', [])
        savings_known = len(assets) > 0
        # For debts, check liabilities
        liabilities = profile.get('liabilities', [])
        debts_asked = len(liabilities) > 0  # If they have debts, we know. If empty after asking, that's OK too.
        # Financial foundation: need income, savings, and debts info
        financial_foundation_complete = income_known and savings_known

        # ===== OTHER GOALS =====
        goals = profile.get('goals', [])
        multiple_goals_explored = len(goals) > 1  # More than just the first mentioned goal

        # Goal-specific fields that should NOT be asked until ready
        goal_specific_fields = ("budget", "deposit", "timeline", "suburbs", "property_type", "borrowing_capacity",
                                "investment_strategy", "goal_planning", "next_steps", "action_plan")

        # Is the LLM trying to jump to goal-specific questions?
        trying_goal_specific = (
            assessment.target_field in goal_specific_fields or
            assessment.next_action in ("goal_planning", "dive_into_goal", "reality_check") or
            assessment.ready_for_goal_planning
        )

        # ===== ENFORCEMENT RULES =====

        # RULE 1: Age MUST be first
        if not age_known:
            logger.warning("ENFORCEMENT: Age unknown - forcing target_field='age'")
            assessment.target_field = "age"
            assessment.current_phase = "persona"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "early"
            assessment.ready_for_goal_planning = False
            assessment.things_to_avoid.append("Don't discuss the goal yet")
            return assessment

        # RULE 2: Relationship next
        if not relationship_known:
            logger.warning("ENFORCEMENT: Relationship unknown - forcing target_field='relationship_status'")
            assessment.target_field = "relationship_status"
            assessment.current_phase = "persona"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "early"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 3: Career next
        if not career_known:
            logger.warning("ENFORCEMENT: Career unknown - forcing target_field='career'")
            assessment.target_field = "career"
            assessment.current_phase = "persona"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "early"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 4: Life aspirations before finances (marriage/family plans)
        if not life_aspirations_complete:
            logger.warning("ENFORCEMENT: Life aspirations incomplete - asking about future plans")
            assessment.target_field = "marriage_plans" if not marriage_known else "family_plans"
            assessment.current_phase = "life_aspirations"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "partial"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 5: Income before goal discussion
        if not income_known:
            logger.warning("ENFORCEMENT: Income unknown - forcing target_field='income'")
            assessment.target_field = "income"
            assessment.current_phase = "financial_foundation"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "partial"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 6: Savings before goal discussion
        if not savings_known:
            logger.warning("ENFORCEMENT: Savings unknown - forcing target_field='savings'")
            assessment.target_field = "savings"
            assessment.current_phase = "financial_foundation"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "partial"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 7: Debts before goal discussion (only if no liabilities recorded yet)
        if not debts_asked:
            logger.warning("ENFORCEMENT: Debts unknown - forcing target_field='debts'")
            assessment.target_field = "debts"
            assessment.current_phase = "financial_foundation"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "partial"
            assessment.ready_for_goal_planning = False
            return assessment

        # RULE 8: Ask about other goals before diving into the mentioned goal
        if not multiple_goals_explored and trying_goal_specific:
            logger.warning("ENFORCEMENT: Only one goal known - asking about other goals first")
            assessment.target_field = "other_goals"
            assessment.current_phase = "goals_overview"
            assessment.next_action = "probe_gap"
            assessment.discovery_completeness = "substantial"
            assessment.ready_for_goal_planning = False
            return assessment

        # All phases complete - goal discussion is now OK
        logger.info("ENFORCEMENT: All phases complete - goal-specific discussion allowed")
        assessment.discovery_completeness = "comprehensive"
        assessment.ready_for_goal_planning = True
        return assessment

    async def _generate_response_from_assessment(
        self,
        username: str,
        user_message: str,
        assessment: ContextAssessment,
        profile: Dict[str, Any],
        user_name: Optional[str] = None
    ) -> str:
        """
        Generate Jamie's response using context assessment.
        Similar to _stage_5_generate_response but uses ContextAssessment.
        """
        logger.info("-" * 40)
        logger.info("RESPONSE GENERATION (from assessment)")
        logger.info("-" * 40)

        agent = self._get_conversation_agent(username, user_name)
        profile_summary = self._format_profile_summary(profile)

        # Build strategy context from assessment
        strategy_context = f"""
ASSESSMENT RESULTS:
- User Intent: {assessment.primary_intent}
- Current Phase: {assessment.current_phase}
- Discovery Completeness: {assessment.discovery_completeness}
- Next Action: {assessment.next_action}
- Target Field: {assessment.target_field or 'None specified'}
- Tone: {assessment.conversation_tone}
- Length: {assessment.response_length}
- Priority Gaps: {', '.join(assessment.priority_gaps) if assessment.priority_gaps else 'None'}
- Things to Avoid: {', '.join(assessment.things_to_avoid) if assessment.things_to_avoid else 'None'}
- Ready for Goal Planning: {assessment.ready_for_goal_planning}
"""

        # Check if we're still in discovery phases (1-3)
        in_discovery = assessment.current_phase in ("persona", "life_aspirations", "financial_foundation", "goals_overview")

        no_goal_ref_rule = """
CRITICAL - NO GOAL REFERENCES:
During discovery, do NOT reference their goal in questions or comments.
BAD: "Is your income stable enough to support the villa?"
GOOD: "Is your income stable?"
BAD: "Any savings? That'll help with the property."
GOOD: "Any savings built up?"
If you're about to type the goal word (house, villa, property, etc.), DELETE IT.
""" if in_discovery else ""

        # Natural phrasing guidance for each target field
        field_guidance = {
            "age": "Ask their age naturally. Example: 'How old are you?' or 'What's your age?'",
            "relationship_status": "Ask if solo or partnered. Example: 'Going solo or with a partner?' or 'Is there a partner involved?'",
            "career": "Ask about work. Example: 'What do you do for work?' or 'What's your work situation?'",
            "marriage_plans": "Ask about future relationship plans. Example: 'Any plans to settle down with someone?' or 'What's on the horizon relationship-wise?'",
            "family_plans": "Ask about kids/family. Example: 'Kids in the picture, now or later?' or 'Any thoughts on family?'",
            "income": "Ask about earnings. Example: 'What's your income like?' or 'What do you earn roughly?'",
            "savings": "Ask about savings. Example: 'Got any savings built up?' or 'What's your savings situation?'",
            "debts": "Ask about debts. Example: 'Any debts to speak of?' or 'Carrying any debts?'",
            "other_goals": "Ask about other financial goals. Example: 'Anything else on your financial wishlist?' or 'Besides that, any other big financial goals?'",
        }

        field_hint = field_guidance.get(assessment.target_field, "")

        prompt = f"""You are Jamie responding to this user message.

USER MESSAGE: {user_message}

{strategy_context}

CURRENT PROFILE:
{profile_summary}

IMPORTANT:
- Follow the next_action directive: {assessment.next_action}
- Ask about: {assessment.target_field}
- {field_hint}
- Use {assessment.conversation_tone} tone
- Keep response {assessment.response_length}
- ONE question maximum - just ask the one thing
- Acknowledge what they just said briefly, then ask your one question
- Don't sound like an interview - be conversational
{no_goal_ref_rule}
Generate your response as Jamie:"""

        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)

            if hasattr(response, 'content'):
                result = response.content
            else:
                result = str(response)

            logger.info(f"Response length: {len(result)} chars")
            return result

        except Exception as e:
            logger.error(f"Response generation error: {e}")
            return "I'm having a bit of trouble right now. Could you say that again?"

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _format_profile_summary(self, profile: Dict[str, Any]) -> str:
        """Format profile for agent context."""
        if not profile:
            return "No profile data available yet."

        parts = []

        # Persona fields (Phase 1) - CRITICAL for context
        if profile.get("age") is not None:
            parts.append(f"Age: {profile['age']}")

        if profile.get("relationship_status"):
            parts.append(f"Relationship: {profile['relationship_status']}")

        if profile.get("has_kids") is not None:
            kids_str = "Has kids" if profile["has_kids"] else "No kids"
            if profile.get("number_of_kids"):
                kids_str += f" ({profile['number_of_kids']})"
            parts.append(kids_str)

        if profile.get("career"):
            parts.append(f"Career: {profile['career']}")

        if profile.get("location"):
            parts.append(f"Location: {profile['location']}")

        # Life aspirations (Phase 2)
        if profile.get("family_plans"):
            parts.append(f"Family plans: {profile['family_plans']}")

        if profile.get("retirement_age"):
            parts.append(f"Target retirement: {profile['retirement_age']}")

        # Financial data (Phase 3)
        if profile.get("income"):
            parts.append(f"Income: ${profile['income']:,.0f}/year")

        if profile.get("goals"):
            goals = [g.get("description", "Unknown") for g in profile["goals"]]
            parts.append(f"Goals: {', '.join(goals)}")

        if profile.get("assets"):
            total_assets = sum(a.get("value", 0) or 0 for a in profile["assets"])
            parts.append(f"Assets: {len(profile['assets'])} items, ~${total_assets:,.0f} total")

        if profile.get("liabilities"):
            total_liabilities = sum(l.get("amount", 0) or 0 for l in profile["liabilities"])
            parts.append(f"Liabilities: {len(profile['liabilities'])} items, ~${total_liabilities:,.0f} total")

        if profile.get("superannuation"):
            total_super = sum(s.get("balance", 0) or 0 for s in profile["superannuation"])
            parts.append(f"Superannuation: ${total_super:,.0f}")

        if profile.get("risk_tolerance"):
            parts.append(f"Risk Tolerance: {profile['risk_tolerance']}")

        return "\n".join(parts) if parts else "Profile exists but limited data collected."
