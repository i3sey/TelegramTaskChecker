# P2P Review & Voting System - Architecture & Flow

## 📊 Current State Analysis

### P2P Review Flow
1. **Initiation** (`cmd_p2p`)
   - Clear state
   - Check if user is STUDENT
   - Get active campaigns where user submitted
   - Filter for P2P type campaigns
   - Show list with progress indicator

2. **Campaign Selection** (`process_p2p_campaign`)
   - Validate campaign is P2P and active
   - Check user has submission in campaign
   - Check if user completed required reviews (done < p2p_reviews_required)
   - Select next submission to review (load-balanced)
   - Send submission file with instructions

3. **Scoring** (`process_p2p_score`)
   - Validate score is in campaign range
   - Prevent score outside bounds
   - Move to comment stage

4. **Commenting** (`process_p2p_comment`)
   - Optional text comment
   - Can skip with button
   - Move to confirmation

5. **Confirmation** (`p2p_confirm`)
   - Check for existing review (prevent duplicates)
   - Create review in database
   - Show progress (done/required)
   - Offer next submission option

6. **Continue** (`p2p_next_`)
   - Similar flow to campaign selection
   - Load-balanced submission selection

---

## 🗳️ Voting Flow
1. **Initiation** (`cmd_vote`)
   - Get active voting campaigns
   - Show all available campaigns

2. **Campaign Selection** (`process_vote_campaign`)
   - Validate campaign type
   - Get first unreviewed submission
   - Determine voting type (like/score)
   - Send submission

3. **Like-type Voting**
   - Simple yes/no buttons
   - Creates review with score=1 for "like"
   - Can skip

4. **Score-type Voting**
   - Input score in range
   - Creates review with given score

5. **Continue** (`vote_next_`)
   - Get next unreviewed submission
   - Repeat voting process

---

## ⚠️ Issues & Limitations

### P2P Review
- ❌ No validation that submission is in UPLOADED status
- ❌ No tracking of review progress by submission (how many reviews it got)
- ❌ No auto-unlock if reviewer never confirms (could block submission)
- ❌ No notification to author when P2P complete
- ❌ Selection algorithm doesn't account for submission author anonymity preference
- ❌ No protection against reviewing same submission multiple times (race condition possible)
- ❌ No limit on time to complete review (can start and never finish)

### Voting
- ❌ No enforcement of vote limits (can vote as many times as wanted)
- ❌ No different voting types properly implemented
- ❌ No statistics on voting results
- ❌ Vote skip doesn't clear state properly in all cases
- ❌ No way to see voting results as organizer

### Both Systems
- ⚠️ Load balancing algorithm could give same submission to multiple reviewers if done simultaneously
- ⚠️ No rate limiting on API calls
- ⚠️ No caching of campaign/submission data
- ⚠️ No error recovery if message send fails mid-flow

---

## ✅ Improvements to Implement

### 1. P2P Review Enhancements
```
VALIDATION LAYER:
├─ Check submission status = UPLOADED (not IN_REVIEW)
├─ Check reviewer hasn't already reviewed this
├─ Check reviewer is not the author
├─ Check campaign is still active and deadline not passed
└─ Check reviewer not banned

REVIEW TRACKING:
├─ Store review attempt with timestamp
├─ Lock submission for reviewer for TTL minutes
├─ Auto-unlock on timeout (Redis)
├─ Notify author when all reviews complete
└─ Show author each review separately

LOAD BALANCING:
├─ Select submission with fewest reviews first
├─ Then by oldest created_at
├─ Randomize if multiple have same review count
└─ Cache selection for session

USER FEEDBACK:
├─ Show "You've reviewed 3/5 required" in real time
├─ Show "This work has 2/3 reviews so far"
├─ Option to view own review after submission
└─ Emoji progress: ⭐⭐⭐⭐☆ (4/5 reviews)

ERROR HANDLING:
├─ Timeout if review not completed in 30 mins
├─ Auto-unlock submission on error
├─ Recover to campaign selection on fail
└─ Log all errors for debugging
```

### 2. Voting Enhancements
```
VOTING TYPES:
├─ LIKE: Simple 👍 / ⏭
├─ BINARY: Да/Нет (Good/Bad)
├─ SCORE: Numeric rating
└─ RANKED: Choose from predefined options

QUOTA SYSTEM:
├─ Set max votes per user per campaign
├─ Show "3 votes left" to user
├─ Prevent voting after quota reached
└─ Reset quota per campaign

RESULTS TRACKING:
├─ Store vote as review with special marker
├─ Calculate statistics:
│  ├─ Total votes
│  ├─ Average score
│  ├─ Vote distribution (histogram)
│  └─ Trending (most liked)
└─ Accessible to organizer

VOTING INTEGRITY:
├─ Cannot vote for own submission
├─ Cannot revote (idempotent)
├─ Can cancel vote within 5 minutes
├─ Session locks to prevent race conditions
└─ Anonymity based on campaign setting
```

### 3. Database Optimization
```
Review table enhancements:
├─ Add column: review_type (expert/p2p/vote)
├─ Add column: is_draft (not final)
├─ Add column: submission_locked_until
├─ Add index on (submission_id, reviewer_id)
└─ Add index on (campaign_id, reviewer_id)

Redis additions:
├─ submission_lock:{submission_id} -> {reviewer_id, timestamp}
├─ reviewer_quota:{campaign_id}:{user_id} -> {votes_left}
├─ session_submission:{user_id}:{campaign_id} -> {submission_id}
└─ TTL-based expiration for all
```

---

## 🎯 Recommended Implementation Order

1. **Phase 1: Stability** (Fixes race conditions)
   - Add submission status validation
   - Add review duplicate check (atomic)
   - Add campaign deadline check
   - Add submission locking (Redis)

2. **Phase 2: UX** (Better feedback)
   - Add progress indicators
   - Add submission review count display
   - Add author notifications
   - Add timeout handling

3. **Phase 3: Features** (New capabilities)
   - Voting types implementation
   - Vote quota system
   - Results tracking
   - Organizer dashboard

4. **Phase 4: Performance** (Optimization)
   - Add caching layer
   - Optimize DB queries
   - Add indexing
   - Rate limiting

---

## 📋 Full Flow Diagrams

### P2P Review Complete Flow
```
START (/p2p)
  ├─ Validate student status ✓
  ├─ Get submitted campaigns (P2P type)
  ├─ Check has submissions ✓
  └─ Display campaign list with progress
      │
      ├─ User selects campaign
      │   └─ Validate campaign active
      │   └─ Check review quota NOT met
      │   └─ Select next submission (load-balanced)
      │   └─ Show submission file
      │   └─ Ask for score
      │       │
      │       ├─ User enters score (validate range)
      │       ├─ Store score in FSM
      │       └─ Ask for comment
      │           │
      │           ├─ User sends comment
      │           ├─ Store comment in FSM
      │           └─ Show confirmation
      │       ├─ User skips comment
      │       ├─ Store None in FSM
      │       └─ Show confirmation
      │           │
      │           ├─ User confirms
      │           │   ├─ Atomic check: review not exists
      │           │   ├─ Create review DB
      │           │   ├─ Update submission status
      │           │   ├─ Count user reviews
      │           │   └─ If done >= required: "All complete!" ELSE: "Next?"
      │           │
      │           ├─ User cancels
      │           │   └─ Clear FSM → Back to campaign list
      │           │
      │           └─ User timeout (>30min)
      │               └─ Force clear → Back to campaign list
      │
      ├─ User clicks "Next submission"
      │   └─ LOOP to submission selection
      │
      ├─ All reviews complete
      │   ├─ Show completion message
      │   └─ Offer back to main menu
      │
      └─ No submissions available
          └─ Show "Come back later"

END
```

### Voting Complete Flow
```
START (/vote)
  ├─ Validate student status ✓
  ├─ Get voting campaigns
  └─ Display campaign list
      │
      ├─ User selects campaign
      │   ├─ Validate campaign active
      │   ├─ Check voting quota (if set)
      │   ├─ Get first unvoted submission
      │   ├─ Determine voting type
      │   └─ Show submission file
      │       │
      │       ├─ IF voting_type == "like"
      │       │   ├─ Show like/skip buttons
      │       │   ├─ User clicks "Like" → score=1 in review
      │       │   └─ User clicks "Skip" → no vote, get next
      │       │
      │       ├─ IF voting_type == "score"
      │       │   ├─ Ask for numeric score
      │       │   ├─ Validate range
      │       │   └─ Create review with score
      │       │
      │       ├─ IF voting_type == "binary"
      │       │   ├─ Show Да/Нет buttons
      │       │   ├─ User clicks → score=1 or score=0
      │       │   └─ Create review
      │       │
      │       └─ Show "Vote counted!" message
      │           │
      │           ├─ IF quota_left > 0
      │           │   └─ "Next?" button
      │           │
      │           ├─ IF quota_left == 0
      │           │   └─ "Voting complete" message
      │           │
      │           └─ User timeout or error
      │               └─ Recover to campaign list
      │
      ├─ User clicks "Next vote"
      │   └─ Get next unvoted submission → LOOP
      │
      └─ No submissions available
          └─ Show "All works voted" or "Come back later"

END
```

---

## 🔐 Safety Checks Summary

```
P2P CHECKS:
✓ Student role only
✓ Must have own submission in campaign
✓ Campaign must be active
✓ Campaign not expired
✓ Reviewer != Author
✓ Submission must be UPLOADED status
✓ No existing review by this reviewer
✓ Score in campaign range
✓ Review quota not met (done < required)

VOTING CHECKS:
✓ Student role only
✓ Campaign must be active
✓ Voter != Author
✓ Submission must be UPLOADED status
✓ No existing vote by this voter
✓ Vote quota not exceeded (if set)
✓ Score in campaign range (if score type)
```

