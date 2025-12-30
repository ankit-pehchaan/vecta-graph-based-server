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

class InformationShared(BaseModel):
    """What information was shared in this message."""
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
        description="Primary intent: sharing_info, stating_goal, asking_question, expressing_emotion, seeking_validation, pushing_back, small_talk, unclear"
    )
    goals_mentioned: List[str] = Field(
        default_factory=list,
        description="ALL goals mentioned (list) - noted for later, not acted on immediately"
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
        description="How complete is our understanding: early (<25%), partial (25-50%), substantial (50-75%), comprehensive (75%+)"
    )
    life_foundation_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about their life: age, family, career, location"
    )
    financial_foundation_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about finances: income, savings, debts, super, insurance"
    )
    goals_gaps: List[str] = Field(
        default_factory=list,
        description="What we don't know about goals: only know one goal, no priorities, no timelines"
    )
    priority_questions: List[str] = Field(
        default_factory=list,
        description="Most important 2-3 things to learn next to build the big picture"
    )
    ready_for_goal_planning: bool = Field(
        default=False,
        description="True ONLY if discovery is substantial (50%+) - don't rush to goal planning"
    )
    contradictions: List[str] = Field(
        default_factory=list,
        description="Conflicting information detected in profile"
    )


class StrategyDecision(BaseModel):
    """Output from Strategy/Router agent - aligned with arch.md."""
    next_action: str = Field(
        ...,
        description="Action: probe_gap, clarify_vague, resolve_contradiction, acknowledge_emotion, redirect_to_discovery, pivot_to_education, answer_direct_question, handle_resistance"
    )
    action_details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details for the action: target_field, probe_approach, clarification_type, etc."
    )
    conversation_tone: str = Field(
        default="warm",
        description="Tone: warm, direct, gentle, encouraging, grounding"
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
        description="Why this is the right move now"
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


class OutputQAIssue(BaseModel):
    """A specific issue found in the response."""
    issue_type: str = Field(..., description="Type: robotic_pattern, directive_miss, compliance, tone, length, multiple_questions, deflection")
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
# PIPELINE ORCHESTRATOR
# =============================================================================

class EducationPipeline:
    """
    Multi-agent pipeline for financial education conversations.

    Orchestrates specialized agents in sequence, with each stage
    adding context and decisions for the next stage.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._agents: Dict[str, Agent] = {}
        self._db_dir = "tmp/agents"
        os.makedirs(self._db_dir, exist_ok=True)

        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

        logger.info("EducationPipeline initialized")

    # -------------------------------------------------------------------------
    # AGENT FACTORY METHODS
    # -------------------------------------------------------------------------

    def _get_intent_classifier(self, username: str) -> Agent:
        """Get or create Intent Classifier agent."""
        key = f"intent_{username}"
        if key not in self._agents:
            self._agents[key] = Agent(
                name="Intent Classifier",
                model=OpenAIChat(id="gpt-4o"),
                instructions=INTENT_CLASSIFIER_PROMPT,
                output_schema=IntentClassification,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Intent Classifier agent for {username}")
        return self._agents[key]

    def _get_qa_validator(self, username: str) -> Agent:
        """Get or create QA/Validator agent."""
        key = f"qa_{username}"
        if key not in self._agents:
            self._agents[key] = Agent(
                name="QA Validator",
                model=OpenAIChat(id="gpt-4o"),
                instructions=QA_VALIDATOR_PROMPT,
                output_schema=ValidationResult,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created QA Validator agent for {username}")
        return self._agents[key]

    def _get_strategy_router(self, username: str) -> Agent:
        """Get or create Strategy/Router agent."""
        key = f"strategy_{username}"
        if key not in self._agents:
            self._agents[key] = Agent(
                name="Strategy Router",
                model=OpenAIChat(id="gpt-4o"),
                instructions=STRATEGY_ROUTER_PROMPT,
                output_schema=StrategyDecision,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Strategy Router agent for {username}")
        return self._agents[key]

    def _get_conversation_agent(self, username: str, user_name: Optional[str] = None) -> Agent:
        """Get or create Conversation Agent (Jamie)."""
        key = f"jamie_{username}"
        if key not in self._agents:
            db_file = os.path.join(self._db_dir, f"jamie_{username}.db")
            instructions = FINANCIAL_ADVISER_SYSTEM_PROMPT
            if user_name:
                instructions += f"\n\nYou're speaking with {user_name}."

            self._agents[key] = Agent(
                name="Jamie (Financial Educator)",
                model=OpenAIChat(id="gpt-4o"),
                instructions=instructions,
                db=SqliteDb(db_file=db_file),
                user_id=username,
                add_history_to_context=True,
                num_history_runs=10,
                markdown=True,
                debug_mode=False
            )
            logger.debug(f"Created Conversation Agent (Jamie) for {username}")
        return self._agents[key]

    def _get_output_qa(self, username: str) -> Agent:
        """Get or create Output QA agent."""
        key = f"output_qa_{username}"
        if key not in self._agents:
            self._agents[key] = Agent(
                name="Output QA",
                model=OpenAIChat(id="gpt-4o"),
                instructions=OUTPUT_QA_PROMPT,
                output_schema=OutputQAResult,
                markdown=False,
                debug_mode=False
            )
            logger.debug(f"Created Output QA agent for {username}")
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

        prompt = f"""Evaluate how complete our understanding of this user is - for their WHOLE life, not just one goal.

USER INTENT: {intent.primary_intent}
GOALS MENTIONED SO FAR: {', '.join(intent.goals_mentioned) if intent.goals_mentioned else 'None yet'}
USER ENGAGEMENT: {engagement}

CURRENT PROFILE:
{profile_summary}

Remember: We need the BIG PICTURE before we can help with ANY specific goal.
Check against the full checklist:
- Life Foundation: age, family, career, location
- Financial Foundation: income, savings, debts, super, insurance
- ALL Goals: not just the one mentioned - what else matters?
- Context: priorities, risk tolerance, what's driving them

Determine:
1. How complete is our understanding overall? (early/partial/substantial/comprehensive)
2. What life foundation gaps exist?
3. What financial foundation gaps exist?
4. What do we not know about their goals (only know one? don't know priorities?)
5. What are the 2-3 most important things to learn next?
6. Are we ready to start goal-specific planning? (Only if discovery is substantial!)"""

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
            logger.info(f"Ready for Goal Planning: {result.ready_for_goal_planning}")
            if result.life_foundation_gaps:
                logger.info(f"Life Foundation Gaps: {', '.join(result.life_foundation_gaps)}")
            if result.financial_foundation_gaps:
                logger.info(f"Financial Foundation Gaps: {', '.join(result.financial_foundation_gaps)}")
            if result.goals_gaps:
                logger.info(f"Goals Gaps: {', '.join(result.goals_gaps)}")
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

        prompt = f"""Decide the conversation strategy - with STRONG bias toward big picture discovery.

USER INTENT: {intent.primary_intent}
EMOTIONAL STATE: {emotional_state} (intensity: {emotional_intensity})
GOALS MENTIONED: {', '.join(intent.goals_mentioned) if intent.goals_mentioned else 'None yet'}

CONVERSATION DYNAMICS:
- User Engagement: {user_engagement}
- Answer Completeness: {answer_completeness}
- Trying to Skip Ahead: {trying_to_skip}

VALIDATION RESULTS:
- Discovery Completeness: {validation.discovery_completeness}
- Ready for Goal Planning: {validation.ready_for_goal_planning}
- Life Foundation Gaps: {', '.join(validation.life_foundation_gaps) if validation.life_foundation_gaps else 'None'}
- Financial Foundation Gaps: {', '.join(validation.financial_foundation_gaps) if validation.financial_foundation_gaps else 'None'}
- Goals Gaps: {', '.join(validation.goals_gaps) if validation.goals_gaps else 'None'}
- Priority Questions: {validation.priority_questions}

CRITICAL RULE: If discovery_completeness is early or partial, we MUST continue discovery.
If only one goal mentioned, we MUST explore other goals before diving into that one.

Return a StrategyDecision with:
1. next_action: probe_gap | clarify_vague | resolve_contradiction | acknowledge_emotion | redirect_to_discovery | pivot_to_education | answer_direct_question | handle_resistance
2. action_details: target_field, probe_approach, framing_hint
3. conversation_tone: warm | direct | gentle | encouraging | grounding
4. response_length: brief | medium | detailed
5. things_to_avoid: list of things NOT to do
6. strategic_reasoning: why this is the right move"""

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

            logger.info(f"Next Action: {result.next_action}")
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
        user_message: str
    ) -> Dict[str, Any]:
        """
        Process a user message through the full education pipeline.

        Returns:
            Dictionary containing:
            - response: The generated response text
            - intent: Intent classification result
            - validation: Validation result
            - strategy: Strategy decision
            - qa_result: Output QA result
            - extracted_data: Any data extracted from message
        """
        logger.info("=" * 60)
        logger.info("EDUCATION PIPELINE START")
        logger.info(f"User: {username}")
        logger.info(f"Message: {user_message}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Get existing profile
        profile = {}
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username) or {}

        # Stage 1: Intent Classification
        intent = await self._stage_1_classify_intent(username, user_message)

        # Stage 2: Data Extraction
        extracted_data = await self._stage_2_extract_data(username, user_message, profile)

        # Refresh profile after extraction
        if extracted_data:
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_username(username) or {}

        # Stage 3: QA/Validation
        validation = await self._stage_3_validate_profile(username, intent, profile)

        # Stage 4: Strategy/Routing
        strategy = await self._stage_4_decide_strategy(username, intent, validation, profile)

        # Stage 5: Response Generation
        response = await self._stage_5_generate_response(
            username, user_message, strategy, intent, profile
        )

        # Stage 6: Output QA
        final_response, qa_result = await self._stage_6_review_output(
            username, user_message, response, strategy
        )

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
            "qa_result": qa_result.model_dump(),
            "extracted_data": extracted_data,
            "duration_seconds": duration
        }

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _format_profile_summary(self, profile: Dict[str, Any]) -> str:
        """Format profile for agent context."""
        if not profile:
            return "No profile data available yet."

        parts = []

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
