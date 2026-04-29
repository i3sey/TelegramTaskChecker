# Refactored Code Structure

## New Organization

The codebase has been reorganized to follow a cleaner, modular structure under `src/bot/`:

### Directory Structure

```
src/
├── bot/                          # Main bot application
│   ├── filters/                  # Filter functions for handlers
│   │   └── __init__.py
│   ├── handlers/                 # Message and command handlers
│   │   ├── __init__.py
│   │   ├── auth_router.py        # Authentication & registration
│   │   ├── campaign_router.py    # Campaign management
│   │   ├── expert_router.py      # Expert review workflow
│   │   ├── organizer_router.py   # Organizer features
│   │   └── student_router.py     # Student actions
│   ├── keyboards/                # Keyboard templates & buttons
│   │   └── __init__.py
│   ├── middlewares/              # Middleware components
│   │   ├── __init__.py
│   │   ├── auth_middleware.py    # User authentication
│   │   └── ban_check.py          # Ban checking
│   ├── models/                   # Database models
│   │   ├── __init__.py
│   │   └── models.py             # SQLAlchemy models
│   ├── services/                 # Business logic services
│   │   ├── __init__.py
│   │   ├── campaign_service.py
│   │   ├── expired_locks.py
│   │   ├── invite_service.py
│   │   ├── notification_service.py
│   │   ├── queue_service.py
│   │   ├── review_service.py
│   │   ├── sheets_service.py
│   │   ├── submission_service.py
│   │   └── user_service.py
│   ├── states/                   # FSM state definitions
│   │   ├── __init__.py
│   │   ├── auth_states.py        # Registration & role change states
│   │   ├── campaign_states.py    # Campaign & submission states
│   │   └── expert_states.py      # Expert review states
│   ├── utils/                    # Utility functions
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   └── validators.py
│   ├── config.py                 # Configuration
│   └── main.py                   # Bot entry point
├── db/                           # Database connection & migrations
│   ├── __init__.py
│   ├── base.py                   # SQLAlchemy Base
│   └── engine.py                 # DB engine & session
├── config.py                     # (still in src/ for backward compat)
└── (other files)

```

## Key Improvements

1. **Clear Separation of Concerns**
   - Handlers in dedicated modules
   - Services isolated for business logic
   - Models centralized in bot/models/
   - States organized by feature

2. **FSM States Extracted**
   - `auth_states.py` - RegistrationStates, RoleChangeStates
   - `campaign_states.py` - CampaignCreationStates, SubmissionStates, OrganizerSessionState
   - `expert_states.py` - ExpertReviewState
   - Centralized `states/__init__.py` for easy imports

3. **Service Layer Reorganized**
   - All services moved to `bot/services/`
   - Services use models from `bot/models/`
   - Services use utils from `bot/utils/`

4. **Backward Compatibility**
   - Old paths in `src/services/`, `src/utils/`, `src/db/models.py` redirect to new locations
   - Existing code continues to work without changes
   - Gradual migration path

## Import Examples

### Old → New

```python
# Old
from src.services.user_service import get_user
from src.utils.logging import logger
from src.db.models import User, UserRole

# New
from src.bot.services.user_service import get_user
from src.bot.utils.logging import logger
from src.bot.models import User, UserRole

# Both work due to backward compatibility shims!
```

## Module Dependencies

```
handlers/
  ├── imports from states/ (FSM definitions)
  ├── imports from services/ (business logic)
  ├── imports from models/ (data models)
  └── imports from utils/ (helpers)

services/
  ├── imports from models/ (data access)
  ├── imports from db/engine.py (DB sessions)
  └── imports from utils/ (logging, etc.)

middlewares/
  ├── imports from services/ (user checks)
  └── imports from utils/ (logging)
```

## Running the Bot

The entry point remains `src/bot/main.py`:

```bash
python -m src.bot.main
```

All imports have been updated to use the new structure automatically!
