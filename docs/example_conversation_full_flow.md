# Vecta Full Conversation Example: Goal Exploration + Fact-Find

> This document demonstrates a complete Phase 1 conversation with the proposed
> Goal Exploration architecture. It shows how the agent naturally moves from
> Socratic goal exploration into contextual fact-finding, extracting data
> implicitly along the way. Australian financial context from the LanceDB
> knowledge base is noted where it influences the agent's questions.

---

## Session Start

**Vecta (greeting):**
> G'day! I'm Vecta, your financial planning assistant. Before we dive into any numbers, I'd love to understand what's on your mind financially. What are you hoping to achieve or work towards?

---

## Phase 0: Goal Exploration

### Goal 1: Investment Property

**User:**
> I want to buy an investment property.

```
[StateResolver extracts]
  - No factual data to extract yet (pure goal statement)

[Orchestrator]
  - ConversationAgent detects goal: "investment_property"
  - Enters GOAL_EXPLORATION mode
  - GoalExplorationAgent takes over
```

---

**Vecta (GoalExplorationAgent, Turn 1 -- Opening Why):**
> Investment property -- that's a popular path here in Australia. What's drawing you to property specifically? Is there something it represents for you beyond the investment itself?

```
[Australian KB retrieved: property.txt]
  "Negative gearing + 50% CGT discount make AU property uniquely
   tax-advantaged vs other countries. Cultural preference for
   property ownership runs deep in Australian financial planning."
  -> Agent aware of cultural context but doesn't mention it;
     uses it to understand why property is default choice for many Australians.
```

---

**User:**
> I want to keep my children safe. Give them something to fall back on.

```
[StateResolver extracts]
  - Dependents.has_children = true        (confidence: 0.85)
  - Dependents.number_of_children >= 1    (confidence: 0.7, "children" plural)

[GoalExplorationAgent internal state]
  goal_layers:
    - surface_goal: "Buy investment property"
    - strategy: "Provide safety net for children"
  emotional_themes: ["family_protection", "security"]
  implicit_facts: {has_children: true}
```

---

**Vecta (GoalExplorationAgent, Turn 2 -- Context Broadening):**
> That makes a lot of sense -- having something tangible for them to fall back on. You mentioned your children -- how many kids do you have, and roughly what ages?

```
[Agent reasoning]
  "User revealed children exist. This is a natural broadening point --
   asking about children count and ages is conversationally appropriate
   and fills Dependents node data without feeling like a form."
```

---

**User:**
> Two kids. 8 and 12. My wife and I both worry about their future.

```
[StateResolver extracts]
  - Dependents.number_of_children = 2       (confidence: 0.95)
  - Dependents.children_ages = [8, 12]      (confidence: 0.95)
  - Personal.marital_status = "married"      (confidence: 0.9, "my wife")
  - Marriage node flagged as relevant        (topology: spouse exists)

[GraphMemory now contains]
  Dependents: {number_of_children: 2, children_ages: [8, 12], has_children: true}
  Personal: {marital_status: "married"}
```

---

**Vecta (GoalExplorationAgent, Turn 3 -- Deepening Why):**
> Eight and twelve -- so the older one's not too far off from thinking about what comes after school. When you picture them being 'safe', is that more about having a roof over their head, financial independence, or something else entirely?

```
[Australian KB retrieved: education.txt]
  "Children aged 12 are ~5 years from university. HECS/HELP covers
   tuition but not living costs. Average uni living costs in Australia
   are $20-25k/year. Property can serve as student housing or
   income source during uni years."
  -> Agent subtly aware that the 12-year-old's education timeline
     intersects with property investment timeline, but doesn't
     lead with this -- lets the user reveal their thinking.
```

---

**User:**
> Financial independence really. I don't want them to struggle like I did starting out.

```
[StateResolver extracts]
  - No new node data (emotional/motivational content)

[GoalExplorationAgent internal state]
  goal_layers:
    - surface_goal: "Buy investment property"
    - strategy: "Provide safety net for children"
    - underlying_need: "Financial independence for children"
    - core_value: "Legacy -- breaking cycle of struggle"
  emotional_themes: ["legacy", "independence", "breaking_cycle"]
  key_quotes: ["I don't want them to struggle like I did starting out"]
```

---

**Vecta (GoalExplorationAgent, Turn 4 -- Reflection + Spouse Pivot):**
> That's a really clear motivation -- giving your kids a head start you didn't have. That kind of clarity actually helps a lot with planning. Does your wife share this vision, or does she see the priorities differently?

```
[Agent reasoning]
  "User has reached core value level (legacy/breaking cycle).
   Natural pivot to spouse -- we know they're married, and
   understanding alignment on goals is critical for planning.
   This also opens the door to spouse financial data."
```

---

**User:**
> She's totally on board. She actually earns more than me -- she works in finance.

```
[StateResolver extracts]
  - Marriage.spouse_occupation = "finance"         (confidence: 0.9)
  - Marriage.spouse_employment_type = "full_time"  (confidence: 0.7, implied)
  - Note: spouse_income > user_income (relative, no absolute number yet)

[GraphMemory now contains]
  Dependents: {number_of_children: 2, children_ages: [8, 12], has_children: true}
  Personal: {marital_status: "married"}
  Marriage: {spouse_occupation: "finance", spouse_employment_type: "full_time"}
```

---

**Vecta (GoalExplorationAgent, Turn 5 -- Strategy Check + Wrap):**
> Nice that you're aligned on it -- and with her finance background, you've probably already been bouncing ideas around. So the way I'm hearing it: the real goal is building financial security and generational wealth for your family, and investment property is one strategy to get there. Have you thought about other approaches too, or is property the main game?

```
[GoalExplorationAgent internal state]
  exploration_complete: approaching
  GoalUnderstanding:
    goal_id: "investment_property"
    surface_goal: "Buy investment property"
    is_strategy_for: "Generational wealth / family financial security"
    underlying_needs: ["financial independence for children", "safety net"]
    core_values: ["legacy", "independence", "family_protection"]
    emotional_themes: ["breaking_cycle", "parental_responsibility"]
    key_quotes:
      - "I want to keep my children safe"
      - "I don't want them to struggle like I did starting out"
    implicit_facts:
      has_children: true
      number_of_children: 2
      children_ages: [8, 12]
      married: true
      spouse_works_in_finance: true
      spouse_income_higher: true
```

---

**User:**
> Property's the main thing. Maybe some shares too, but property feels more real to me.

```
[StateResolver extracts]
  - Possible secondary goal hint: wealth_creation via shares
    (not strong enough to register as explicit goal, stored as context)

[GoalExplorationAgent]
  - Exploration complete for this goal
  - "shares" noted as potential sub-strategy but not a separate goal
  - Transition to asking for more goals
```

---

**Vecta (GoalExplorationAgent, Turn 6 -- Transition):**
> Fair enough -- property's tangible, you can see it and touch it. I've got a solid picture of what's driving this for you. Beyond the property, are there any other financial goals or things keeping you up at night?

---

### Goal 2: Retirement

**User:**
> Yeah, retirement I suppose. Want to make sure we're sorted when we stop working.

```
[StateResolver extracts]
  - No new factual data (goal statement)

[Orchestrator]
  - New goal detected: "retirement"
  - Stays in GOAL_EXPLORATION mode
  - GoalExplorationAgent explores this goal
```

---

**Vecta (GoalExplorationAgent, Turn 1 for Goal 2 -- Opening Why):**
> Retirement's a big one. When you say 'sorted', what does retirement actually look like for you two? Are you picturing kicking back at home, travelling, or something else?

```
[Australian KB retrieved: retirement.txt]
  "Preservation age ranges 55-60 depending on birth year.
   Age Pension currently ~$28k/year single, ~$42k/year couple.
   ASFA comfortable retirement standard: ~$72k/year couple.
   Most Australians underestimate retirement income needs."
  -> Agent knows benchmarks but doesn't quote them; asks user
     to articulate their own vision first.
```

---

**User:**
> Travelling mainly. We've always said once the kids are sorted we want to see the world. Spend time with each other, maybe spend a few months in Europe.

```
[StateResolver extracts]
  - No new node data (lifestyle/emotional content)
  - Note: travel is a sub-goal within retirement, not separate

[GoalExplorationAgent internal state]
  goal_layers:
    - surface_goal: "Retirement planning"
    - strategy: "Build corpus to fund retirement lifestyle"
  emotional_themes: ["freedom", "togetherness", "delayed_gratification"]
```

---

**Vecta (GoalExplorationAgent, Turn 2 -- Deepening Why):**
> A few months in Europe -- sounds like you've been thinking about this for a while. Genuine question though: why wait for retirement? Is travelling something you'd want to do more of now too, or is it specifically a 'when the kids are grown' thing?

```
[Agent reasoning]
  "This is the 'turnaround' technique from the architecture spec.
   User said travel is for retirement. But travel might actually be
   a standalone goal or current desire being deferred. Challenging
   the assumption can reveal whether retirement is the real goal
   or if it's a proxy for 'permission to enjoy life'."
```

---

**User:**
> Hah, good point. We do travel a bit now -- a week in Bali last year, Gold Coast over Christmas. But the big trips, the three-month Europe kind of thing, that needs retirement money and retirement time.

```
[StateResolver extracts]
  - Expenses hint: travel is already a spending category
    (not extracted as hard number, but noted for Expenses node later)

[GoalExplorationAgent internal state]
  goal_layers:
    - surface_goal: "Retirement planning"
    - strategy: "Build corpus for comfortable retirement with travel"
    - underlying_need: "Freedom to travel extensively without time/money constraints"
    - core_value: "Freedom, togetherness with spouse"
  emotional_themes: ["freedom", "togetherness", "reward_after_sacrifice"]
  key_quotes: ["the big trips need retirement money and retirement time"]
```

---

**Vecta (GoalExplorationAgent, Turn 3 -- Practical Context):**
> Makes sense -- the short trips scratch the itch but the big adventures need a different setup. Roughly what age are you thinking for when you'd want to make that switch? And how old are you both now, just so I've got context?

```
[Agent reasoning]
  "User has articulated clear retirement vision. Natural to ask
   age and target retirement age -- these are Personal node fields
   but feel organic in this conversation context."
```

---

**User:**
> I'm 42, she's 39. Ideally I'd love to be done by 60, maybe earlier if we can swing it.

```
[StateResolver extracts]
  - Personal.age = 42                         (confidence: 0.95)
  - Marriage.spouse_age = 39                   (confidence: 0.95)
  - Retirement.target_retirement_age = 60      (confidence: 0.85)

[GraphMemory now contains]
  Dependents: {number_of_children: 2, children_ages: [8, 12], has_children: true}
  Personal: {marital_status: "married", age: 42}
  Marriage: {spouse_occupation: "finance", spouse_employment_type: "full_time",
             spouse_age: 39}
  Retirement: {target_retirement_age: 60}
```

---

**Vecta (GoalExplorationAgent, Turn 4 -- Wrap Goal 2):**
> Done by 60, so about 18 years to build towards that. With the kids being 8 and 12, they'd be well into their own lives by then too -- so the property goal and the retirement goal actually connect quite nicely. I've got a good sense of what retirement means for you. Anything else on the list, or are those the big two?

```
[GoalExplorationAgent]
  GoalUnderstanding for retirement:
    goal_id: "retirement"
    surface_goal: "Retirement planning"
    is_strategy_for: null (this IS the core goal)
    underlying_needs: ["freedom to travel extensively", "time together as couple"]
    core_values: ["freedom", "togetherness", "reward_after_sacrifice"]
    emotional_themes: ["delayed_gratification", "partnership"]
    key_quotes:
      - "once the kids are sorted we want to see the world"
      - "the big trips need retirement money and retirement time"
    implicit_facts:
      age: 42
      spouse_age: 39
      target_retirement_age: 60
      already_travels_short: true
```

---

**User:**
> That's the main two. Oh actually, we should probably sort out our insurance situation too. I know we've got some through work but I've never really looked at it properly.

```
[StateResolver extracts]
  - Insurance.coverages hint: has employer-provided insurance (unspecified type)
    (confidence: 0.6, "some through work")

[Orchestrator]
  - New goal detected: "insurance_review" (type: other/protection)
  - Brief exploration, not deep Socratic since user framed it
    as administrative rather than emotionally driven
```

---

**Vecta (GoalExplorationAgent, Turn 1 for Goal 3 -- Light Touch):**
> Good call -- a lot of people have insurance through their super or employer and have no idea what it actually covers. Is there something specific that's made you think about it, or more of a 'should probably check' feeling?

---

**User:**
> Just a 'should probably check' thing really. A mate at work had a health scare and it made me think.

```
[StateResolver extracts]
  - No hard data, but context noted: health scare awareness,
    possible gap in understanding of current cover

[GoalExplorationAgent]
  - Light exploration -- user isn't deeply emotionally invested,
    more practical/administrative
  - Goal understood: review and potentially upgrade insurance coverage
  - Exploration complete quickly (2 turns)
```

---

**Vecta (GoalExplorationAgent, Turn 2 -- Confirm + Close):**
> That's actually how most people end up looking at it -- someone else's wake-up call. No worries, we'll make sure we get a clear picture of what you've got and whether there are any gaps. So those three -- investment property, retirement, and sorting out insurance. Anything else, or are we good to dive in?

---

**User:**
> That's it. Let's go.

```
[Orchestrator]
  - goals_collection_complete = true
  - Three qualified goals:
    1. investment_property (priority: 1)
       - GoalUnderstanding attached (deep exploration)
    2. retirement (priority: 2)
       - GoalUnderstanding attached (deep exploration)
    3. insurance_review (priority: 3)
       - Light exploration (practical, not emotional)
  - Exit GOAL_EXPLORATION mode
  - Enter DATA_GATHERING mode (fact-find)

  DATA ALREADY COLLECTED IMPLICITLY:
  +-----------------+----------------------------------------------+
  | Personal        | age: 42, marital_status: married             |
  | Marriage        | spouse_age: 39, spouse_occupation: finance,  |
  |                 | spouse_employment_type: full_time             |
  | Dependents      | number_of_children: 2, children_ages: [8,12],|
  |                 | has_children: true                            |
  | Retirement      | target_retirement_age: 60                    |
  | Insurance       | (hint: has employer-provided, details unknown)|
  +-----------------+----------------------------------------------+

  NODES ALREADY PARTIALLY FILLED: 4 of 10
  EMOTIONAL CONTEXT AVAILABLE FOR ALL FUTURE QUESTIONS
```

---

## Phase 1: Contextual Fact-Find

> **Key difference from current system**: The agent now knows the user's emotional
> drivers, family situation, and goals deeply. Every question is informed by this
> context. No "Do you have children?" (we already know). No "Are you married?"
> (we already know). The conversation feels like a continuation, not a restart.

---

### Branch 1: Life Topology (Personal, Marriage, Dependents)

**Vecta (ConversationAgent -- Personal node):**
> Great, let's build out the full picture. I already know you're 42 and married. What do you do for work? And is it full-time, part-time, contract?

```
[Context-aware reasoning]
  "Personal node needs: occupation, employment_type.
   Age and marital_status already filled from exploration.
   Don't re-ask those. Jump to missing fields."
```

---

**User:**
> I'm a project manager in construction. Full-time.

```
[StateResolver extracts]
  - Personal.occupation = "project manager"          (confidence: 0.95)
  - Personal.employment_type = "full_time"           (confidence: 0.95)

[Personal node: COMPLETE]
  {age: 42, marital_status: "married", occupation: "project manager",
   employment_type: "full_time"}
```

---

**Vecta (ConversationAgent -- Marriage node):**
> Nice, construction PM -- solid industry here in Australia. You mentioned your wife works in finance and earns more than you. Do you know roughly what her annual income is? And are your finances combined or do you keep things separate?

```
[Context-aware reasoning]
  "Marriage node needs: spouse_income_annual, finances_combined.
   Already have spouse_age, spouse_occupation, spouse_employment_type
   from exploration. Reference what we know naturally."

[Australian KB retrieved: tax.txt]
  "Combined household income determines Medicare levy surcharge
   thresholds, family tax benefit eligibility, and private health
   insurance rebate tiers."
  -> Agent doesn't mention this but knows spouse income matters
     for holistic planning.
```

---

**User:**
> She's on about 140k. We keep a joint account for bills and mortgage but have our own spending money.

```
[StateResolver extracts]
  - Marriage.spouse_income_annual = 140000      (confidence: 0.95)
  - Marriage.finances_combined = "partial"      (confidence: 0.9)
  - Loan hint: "mortgage" mentioned             (Loan node flagged)

[Marriage node: COMPLETE]
  {spouse_age: 39, spouse_occupation: "finance",
   spouse_employment_type: "full_time", spouse_income_annual: 140000,
   finances_combined: "partial"}
```

---

**Vecta (ConversationAgent -- Dependents node):**
> Good setup. I've got your two kids down -- 8 and 12. Are they at public school, private, Catholic? And are you supporting anyone else financially -- parents or anyone?

```
[Context-aware reasoning]
  "Dependents has number_of_children and ages from exploration.
   Missing: education_type, supporting_parents.
   Don't ask 'do you have children' -- we've been talking about
   them for 10 minutes. Ask the missing specific fields."

[Australian KB retrieved: education.txt]
  "Private school average: $15-25k/year. Catholic: $5-10k/year.
   Public: minimal direct costs. Private school families often
   have education as a significant expense category."
```

---

**User:**
> Both at a Catholic school. About 8 grand a year total for the two of them. No, not supporting parents -- they're both pretty self-sufficient.

```
[StateResolver extracts]
  - Dependents.education_type = "catholic"             (confidence: 0.95)
  - Dependents.supporting_parents = false              (confidence: 0.95)
  - Expenses.monthly_expenses["education"] = 667       (8000/12, confidence: 0.9)

[Dependents node: COMPLETE]
  {number_of_children: 2, children_ages: [8, 12], has_children: true,
   education_type: "catholic", supporting_parents: false}
```

---

### Branch 2: Income & Expenses

**Vecta (ConversationAgent -- Income node):**
> Catholic school, good stuff. Now let's talk money coming in. What's your annual salary? And do you have any other income besides your main job -- rental, dividends, anything like that?

```
[Context-aware reasoning]
  "Income node is empty. Open-ended portfolio question for
   income_streams_annual. User is construction PM full-time,
   wife in finance on 140k. No rental income yet (they want
   to BUY an investment property, so presumably don't have one)."
```

---

**User:**
> I'm on 125k plus super. No other income for me -- she's got about 5k a year in dividends from some shares she had before we got together.

```
[StateResolver extracts]
  - Income.income_streams_annual["salary"] = 125000        (confidence: 0.95)
  - Marriage.spouse_income_annual = 140000                  (already stored, confirmed)
  - Income.income_streams_annual["spouse_dividends"] = 5000 (confidence: 0.85)
  - Assets hint: spouse has shares                          (for Assets node later)

[Income node: COMPLETE]
  {income_streams_annual: {salary: 125000, spouse_dividends: 5000}}
```

---

**Vecta (ConversationAgent -- Expenses node):**
> So household income of about 270k between the two of you -- solid base. Roughly what do your monthly expenses look like? The big ones -- mortgage, bills, groceries, the school fees we already mentioned, and anything else that chews through the budget.

```
[Context-aware reasoning]
  "Expenses node needs monthly_expenses dict. Already have
   education at $667/month from earlier. User mentioned mortgage
   so that's definitely a category. Open-ended question to
   capture as much as possible in one answer."
```

---

**User:**
> Mortgage is about 3,200 a month. Groceries and food maybe 1,500. Bills -- electricity, water, internet, phones -- probably 600. Car costs about 400 between fuel and insurance. Then just general spending, entertainment, kids activities, probably another 1,500.

```
[StateResolver extracts]
  - Expenses.monthly_expenses = {
      "education": 667,          (already stored, preserved via merge)
      "rent_mortgage": 3200,
      "food": 1500,
      "utilities": 600,
      "transport": 400,
      "entertainment": 1500
    }

[Expenses node: COMPLETE]
  Total monthly: ~$7,867 (~$94k/year)
```

---

**Vecta (ConversationAgent -- Savings node):**
> So about 7,800 a month going out. That leaves a decent chunk from your combined income. How much have you got sitting in savings right now? And is any of that in an offset account against the mortgage?

```
[Australian KB retrieved: superannuation.txt]
  "Offset accounts reduce mortgage interest while keeping
   funds liquid. Common Australian strategy -- effectively
   earns the mortgage interest rate tax-free on savings."
  -> Agent asks about offset specifically because it's a
     uniquely Australian product and the user has a mortgage.
```

---

**User:**
> About 45k in a regular savings account and 30k in the offset. So 75k all up in cash.

```
[StateResolver extracts]
  - Savings.total_savings = 75000                 (confidence: 0.95)
  - Savings.offset_balance = 30000                (confidence: 0.95)
  - Assets.asset_current_amount["cash_deposits"] = 75000 (dual mapping)

[Savings node: COMPLETE]
  {total_savings: 75000, offset_balance: 30000}
```

---

### Branch 3: Wealth (Assets, Loans)

**Vecta (ConversationAgent -- Assets node):**
> 75k in cash with 30 in the offset -- smart use of the offset. Beyond the cash and your home, what other assets do you and your wife have? You mentioned she's got some shares. What about super balances, any other investments?

```
[Context-aware reasoning]
  "Assets node needs asset_current_amount portfolio.
   Already know: cash_deposits from Savings, spouse has shares
   (mentioned during income). Home exists (mortgage mentioned).
   Need: property value, super balances, shares value, anything else."
```

---

**User:**
> The house is worth about 950k. Her shares are worth maybe 40k now. My super is about 180k, hers is around 220k. That's about it really.

```
[StateResolver extracts]
  - Assets.asset_current_amount = {
      "cash_deposits": 75000,     (preserved from Savings)
      "property": 950000,
      "stocks_etfs": 40000,
      "superannuation": 400000    (combined: 180k + 220k)
    }
  - Retirement.super_balance = 180000          (user's own)
  - Marriage.spouse_super_balance = 220000

[Assets node: COMPLETE]
  {asset_current_amount: {cash_deposits: 75000, property: 950000,
   stocks_etfs: 40000, superannuation: 400000}}
```

---

**Vecta (ConversationAgent -- Loan node):**
> Good picture. You mentioned the mortgage -- what's the outstanding balance on that? And do you have any other debts -- car loan, credit cards, HECS, anything like that?

```
[Australian KB retrieved: property.txt]
  "Average Australian mortgage ~$600k. LVR (loan-to-value ratio)
   important for investment property borrowing capacity.
   HECS/HELP repayment thresholds start at ~$54k income."
```

---

**User:**
> Mortgage is about 520k, still got 22 years on it. Interest rate is 6.2%. I've still got about 15k in HECS left. No credit card debt, we pay that off each month. She cleared her HECS years ago.

```
[StateResolver extracts]
  - Loan.liabilities = {
      "home_loan": {
        outstanding_amount: 520000,
        remaining_term_months: 264,   (22 years * 12)
        interest_rate: 0.062,
        monthly_payment: 3200         (from expenses, linked)
      },
      "hecs_help": {
        outstanding_amount: 15000
      }
    }

[Loan node: COMPLETE]
  {liabilities: {home_loan: {...}, hecs_help: {outstanding_amount: 15000}}}
```

---

### Branch 4: Protection (Insurance, Retirement)

**Vecta (ConversationAgent -- Insurance node):**
> Nice work on the credit card discipline. Now let's look at that insurance situation you wanted to sort out. You said you've got some through work -- do you know what type? Life, income protection, TPD? And does your wife have cover too?

```
[Context-aware reasoning]
  "User explicitly listed insurance_review as goal #3.
   They said they had 'some through work' during exploration.
   This is emotionally relevant to them (mate's health scare).
   Ask open-ended to capture whatever they know."

[Australian KB retrieved: insurance_au.txt]
  "Most employer super funds include default life and TPD cover.
   Income protection less common in default cover. Many Australians
   are underinsured -- average life cover through super is ~$200k
   which is often inadequate for mortgage + family."
```

---

**User:**
> I think I've got life and TPD through my super -- maybe 400k on the life? Not sure about the exact TPD amount. I don't think I have income protection. She's got life through her super too but I don't know the amount. We've got private health -- family cover, about 350 a month.

```
[StateResolver extracts]
  - Insurance.coverages = {
      "life": {
        covered_person: "self",
        held_through: "super",
        coverage_amount: 400000
      },
      "tpd": {
        covered_person: "self",
        held_through: "super"
      },
      "private_health": {
        covered_person: "family",
        held_through: "personal",
        premium_amount: 350,
        premium_frequency: "monthly"
      }
    }
  - Insurance.has_life_insurance = true
  - Insurance.has_tpd_insurance = true
  - Insurance.has_income_protection = false
  - Insurance.has_private_health = true
  - Insurance.spouse_has_life_insurance = true

[Insurance node: COMPLETE (primary field 'coverages' answered)]
```

---

**Vecta (ConversationAgent -- Retirement node):**
> Good that you've got some cover in place -- we'll come back to whether there are gaps when we review everything. Last piece of the puzzle: super. You said yours is about 180k and hers is 220k. Do you know who your funds are with? And are either of you salary sacrificing any extra into super, or just the standard employer contributions?

```
[Context-aware reasoning]
  "Retirement node has target_retirement_age (60) from exploration
   and super_balance (180k) from assets discussion. Missing:
   fund names, salary sacrifice, contribution details."

[Australian KB retrieved: superannuation.txt]
  "Employer SG rate is 12% (2025-26). Concessional contribution
   cap is $30k/year. At 42 with $180k super targeting retirement
   at 60, additional contributions may be needed to reach
   comfortable retirement. 18 years of compounding available."
```

---

**User:**
> Mine's with AustralianSuper, hers is with Sunsuper -- well, Australian Retirement Trust now. Neither of us salary sacrifice anything, just the standard employer 12%.

```
[StateResolver extracts]
  - Retirement.super_fund = "AustralianSuper"
  - Retirement.employer_contribution_rate = 0.12
  - Retirement.salary_sacrifice_monthly = 0
  - Retirement.personal_contribution_monthly = 0
  - Marriage.spouse_super_fund = "Australian Retirement Trust"

[Retirement node: COMPLETE]
  {super_balance: 180000, target_retirement_age: 60,
   super_fund: "AustralianSuper", employer_contribution_rate: 0.12,
   salary_sacrifice_monthly: 0, personal_contribution_monthly: 0}
```

---

## Goal Inference Trigger

```
[Orchestrator: All nodes complete]
  Visited: Personal, Marriage, Dependents, Income, Expenses, Savings,
           Assets, Loan, Insurance, Retirement
  Pending: none

[GoalInferenceAgent runs on complete baseline]
  Visited node snapshots analysed...

  INFERRED GOALS:
  1. emergency_fund (confidence: 0.82)
     - Total savings: $75k, monthly expenses: $7,867
     - Emergency buffer: ~9.5 months (healthy but offset-dependent)
     - If offset is drawn, mortgage interest increases
     Evidence: ["savings_75k", "monthly_expenses_7867", "offset_30k_linked_to_mortgage"]

  2. child_education (confidence: 0.78)
     - Two children aged 8 and 12
     - 12-year-old approaching uni in ~5 years
     - No dedicated education savings evident
     Evidence: ["children_ages_8_12", "no_education_savings", "catholic_school_current"]

  3. income_protection (confidence: 0.88)
     - Primary earner in construction (physical work risk)
     - No income protection cover
     - Mortgage $520k + 2 dependents + spouse income would need supplementing
     Evidence: ["no_income_protection", "construction_pm", "mortgage_520k", "2_dependents"]

  Trigger scenario framing for: income_protection (highest confidence, critical gap)
```

---

## Scenario Framing: Income Protection

**Vecta (ScenarioFramerAgent, Turn 1):**
> Quick tangent while we're pulling this together -- you mentioned you don't have income protection. With the construction industry and a 520k mortgage, if something happened and you couldn't work for a few months, how would you and your wife manage the bills on just her income?

---

**User:**
> Yeah, that's a good point actually. Her 140k would cover the basics but it'd be tight. We'd burn through that savings pretty quick with the mortgage and school fees and everything.

---

**Vecta (ScenarioFramerAgent, Turn 2 -- Confirm):**
> Exactly -- you'd go from comfortable to watching every dollar pretty fast. Want me to add income protection as something we factor into the plan?

---

**User:**
> Yeah, definitely add that.

```
[Orchestrator]
  - income_protection goal CONFIRMED -> qualified_goals
  - Next scenario: child_education
```

---

## Scenario Framing: Child Education

**Vecta (ScenarioFramerAgent, Turn 1):**
> One more thought -- your 12-year-old is about 5 years from potentially heading to uni. Even with HECS covering tuition, living costs, textbooks, and everything else can add up to 20-25k a year. Is that something you'd want to plan for, or are you thinking they'll sort themselves out with HECS and part-time work?

```
[Australian KB retrieved: education.txt]
  "HECS/HELP covers tuition fees (repaid through tax system).
   But living costs for uni students: rent, food, transport,
   textbooks average $20-25k/year in capital cities. Many
   parents want to support children through uni to avoid
   excessive part-time work affecting grades."
```

---

**User:**
> We'd definitely want to help them. Probably cover their living costs at least -- we don't want them working 30 hours a week just to survive at uni.

---

**Vecta (ScenarioFramerAgent, Turn 2 -- Confirm):**
> Totally fair. Want me to add education planning for both kids as a goal? We can work out the specifics when we crunch the numbers.

---

**User:**
> Yeah, go for it.

```
[Orchestrator]
  - child_education goal CONFIRMED -> qualified_goals
  - No more scenarios in queue (emergency_fund skipped -- 9.5 months
    buffer is healthy, lower priority)
  - Exit scenario framing
```

---

## Goal Details Collection

**Vecta (GoalDetailsAgent):**
> Awesome. Let's nail down some specifics. For the investment property -- do you have a rough budget in mind? And when are you thinking of buying?

---

**User:**
> We're thinking around the 600-700k mark. Hopefully within the next 2-3 years.

```
[GoalDetailsAgent extracts]
  - investment_property.target_amount = 650000  (midpoint)
  - investment_property.timeline_years = 2      (conservative end)
```

---

**Vecta (GoalDetailsAgent):**
> And for retirement -- you said ideally by 60. Any sense of what annual income you'd want in retirement? Travel-heavy lifestyle won't be cheap!

---

**User:**
> I reckon we'd want at least 80k a year to live comfortably and travel. Maybe more.

```
[GoalDetailsAgent extracts]
  - retirement.desired_income = 80000
  - retirement.target_year = 2044  (42 + 18 = 60, current year + 18)
```

---

**Vecta (GoalDetailsAgent):**
> 80k a year with some travel budget on top -- realistic for what you're describing. For the kids' education, are you thinking you'd cover full living costs, or more of a 50/50 split with them working part-time?

---

**User:**
> Probably 70/30 -- we'd cover most of it but they should learn to earn a bit too.

```
[GoalDetailsAgent extracts]
  - child_education.funding_method = "70_parent_30_child"
  - child_education.target_year = 2031  (12-year-old in 5 years)
```

---

## Phase 1 Complete

**Vecta (ConversationAgent -- Phase 1 Summary):**
> That covers everything I need to start putting the picture together for you. Here's where we're at:
>
> **Your goals:**
> 1. Investment property (~$650k, within 2-3 years) -- driven by building generational wealth and security for your kids
> 2. Retirement by 60 (~$80k/year lifestyle with travel) -- you and your wife want freedom to see the world together
> 3. Insurance review -- making sure you're properly covered, especially income protection
> 4. Children's education -- supporting both kids through uni (you covering ~70%)
>
> **Your situation snapshot:**
> - Household income: ~$270k (you $125k + wife $140k + $5k dividends)
> - Monthly expenses: ~$7,900
> - Savings: $75k (including $30k in offset)
> - Home: $950k (mortgage $520k at 6.2%, 22 years remaining)
> - Super: $400k combined (yours $180k, hers $220k) -- employer contributions only
> - Insurance: Life + TPD through super, private health (family), no income protection
> - HECS: $15k remaining
>
> From here I can run some projections and show you how the numbers stack up against your goals. Want to start with any particular goal, or shall I work through them in priority order?

```
[Orchestrator]
  phase1_complete: true
  All nodes visited: 10/10
  Qualified goals: 4 (investment_property, retirement, insurance_review, child_education)
  + GoalUnderstanding documents for emotional context

  TOTAL CONVERSATION TURNS: ~30
  IMPLICIT DATA EXTRACTED DURING EXPLORATION: 8 fields across 4 nodes
  EXPLICIT FACT-FIND QUESTIONS SAVED: ~4 questions (didn't need to ask
    about age, marital status, children existence, retirement age)
```

---

## Architecture Summary: What Made This Different

### During Goal Exploration (Turns 1-20)
| Aspect | Old System | New System |
|--------|-----------|------------|
| Goal intake | "Any more goals?" | 5-7 turn Socratic "why" exploration per goal |
| Data collection | Zero during goal phase | 8 fields extracted implicitly |
| Emotional understanding | None | Full goal ontology with values + themes |
| Goal vs strategy | Not distinguished | "Property = strategy for generational wealth" |
| Australian context | Not used | KB retrieval informed smarter questions |
| Conversation feel | Form-filling | Natural human conversation |

### During Fact-Find (Turns 21-30)
| Aspect | Old System | New System |
|--------|-----------|------------|
| Opening questions | "How old are you?" | "I already know you're 42..." |
| Redundant questions | Many (re-ask what goals revealed) | Zero (exploration data pre-filled) |
| Context awareness | Generic questions | Questions reference user's goals + emotions |
| Australian specifics | In prompt only | KB retrieval for offset, HECS, super details |
| Question count | ~15-20 questions | ~10 questions (exploration pre-filled rest) |

### Data Flow

```
Goal Exploration Conversation
        |
        v
[StateResolver runs on EVERY user message]
        |
        +---> GraphMemory (implicit facts: age, kids, married, etc.)
        |
        +---> GoalUnderstanding (emotional context, ontology, quotes)
        |
        v
Contextual Fact-Find
        |
        v
[Questions skip already-known fields]
[Questions reference emotional context]
[Australian KB adds specificity]
        |
        v
Goal Inference (on node completion)
        |
        v
Scenario Framing (for inferred goals)
        |
        v
Goal Details Collection
        |
        v
Phase 1 Complete
```
