# Market, Event, and War Commands: Stellaris 4.4.6

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Scope

This note narrows the long-running Linux `human_ai` capture to three command
families requested for the native runtime:

- market buy and sell;
- AI selection of event options;
- claims, diplomatic responses, and declaration of war.

The target is Stellaris `Pegasus v4.4.6 (fdde)`, Linux ELF Build ID
`c6969e60fd81d738948222a94c0b5a0841abbffc`. The capture is passive. Counts
below prove native submission and execution lifecycles, not that an action is
safe to expose to an Application.

The completed campaign reached `2504.04.01`. Its durable catalog plus final
unrotated tail contain 2,153,069 command records and 2,479,691 bounded payload
records, with zero reported pipe, writer, or malformed-record loss.

## Runtime implementation status

The first typed adapters are now present in the production native-runtime
tree:

| Semantic surface | Native implementation | Broker status |
| --- | --- | --- |
| `market_buy_resource(resource_key, lots)` | self-registered Linux 4.4.6 action | Broker enabled (`live_verified`) |
| `market_sell_resource(resource_key, lots)` | self-registered Linux 4.4.6 action | Broker enabled (`live_verified`) |
| `inspect_open_events(country_id)` | read-only runtime query | callable through `NativeRuntimeClient` |
| `select_event_option(open_event_id, option_index)` | self-registered Linux 4.4.6 action | Broker enabled (`live_verified`) |
| `inspect_pending_diplomatic_actions(country_id)` | read-only runtime query | callable through `NativeRuntimeClient` |
| `respond_to_diplomatic_action(pending_action_id, accept)` | self-registered Linux 4.4.6 action | Broker enabled (`live_verified`) |
| `vote_on_diplomatic_action(pending_action_id, support)` | self-registered Linux 4.4.6 action | discoverable, disabled (`paired_capture`) |

The `uint64` pending-action identifier is represented end to end in the C++
manifest, Python runtime contract and dynamic Broker overlay. Focused embassy
and immediate-trade tests have since exercised both accept and reject and
verified their save continuations, so the response action is enabled. The
separate federation-style vote remains `paired_capture` and keeps
`broker_enabled_backends` empty.

`inspect_open_events` is deliberately separate from the side-effect Action
Registry. It accepts an explicit country ID so observer tooling can inspect an
AI country's pending events without pretending to hold execution authority.
It returns the exact open-event instance ID, event-definition ID, stable title
localization key, and each currently legal option index plus stable option key.
The result schema is `iag.open_event_state.v1`.

The query does not call `CEvent::GetDesc` or the option's dynamic display-name
renderer. Static analysis showed those paths can reach `CCrudeRandom::Seed`
and the process RNG. A supposedly read-only inspector must not perturb the
simulation. The first production interface therefore reports
`content_mode=stable_keys_no_rng` and marks the description
`dynamic_unrendered`; external localization and variable substitution can be
added later behind a separately verified, deterministic resolver.

`inspect_pending_diplomatic_actions` follows the same candidate-first rule for
incoming diplomacy. It returns each current action's 64-bit stable ID, native
action tag, actor and recipient country IDs, plus the results of Stellaris'
own accept/reject legality checks. It does not propose diplomacy, vote, accept,
reject, or confer execution authority. The result schema is
`iag.pending_diplomatic_action_state.v1`.

## Observed command activity

| Native type | `session_post` | `execute_sync` | Interpretation |
| --- | ---: | ---: | --- |
| `CMarketBuyResourceCommand` | 23,811 | 23,792 | Final one-shot market purchase |
| `CMarketSellResourceCommand` | 16,155 | 15,779 | Final one-shot market sale; posting is not success evidence |
| `CPutSlaveOnMarketCommand` | 97 | 97 | Separate slave-market family |
| `CBuySlaveFromMarketCommand` | 76 | 74 | Separate slave-market family |
| `CSelectEventOptionCommand` | 1,045 | 1,045 | Final event-option selection |
| `CExecuteEventAfterCommand` | 7 | 7 | Engine scheduling, not a player semantic action |
| `CDiploActionProposeCommand` | 2,394 | 2,394 | Polymorphic diplomatic-action wrapper |
| `CDiploActionRespondCommand` | 946 | 939 | Accept or reject a pending diplomatic action |
| `CDiploActionVoteCommand` | 287 | 287 | Vote on a diplomatic action |
| `CAIPrepareWarCommand` | 25 | 25 | AI planning state, not declaration of war |
| `CAddSystemClaimCommand` | 117 | 117 | Add a system claim |
| `CRemoveSystemClaimCommand` | 18 | 18 | Remove a system claim |
| `CDiploActionSetDefenderWarGoalCommand` | 8 | 8 | Select a defender goal after war creation |
| `CAIUpdateStrategicWarData` | 68,026 | 68,026 | Internal AI strategy state |

The unequal market-sell and diplomatic-response counts are an important
control. A successful call to `PostCommandToSession` cannot be treated as an
authoritative game-state confirmation.

## Market buy and sell

### Recovered native layout

The two command objects are each `0x40` bytes:

```text
CCommand common header       +0x00 .. +0x1b
STradeData                    +0x20 .. +0x37
trade lot count (int)         +0x38
```

`STradeData` is:

```text
vptr                          +0x00
CStrategicResource*           +0x08
EMarketTradeType              +0x10   # 0 buy, 1 sell
TPdxRef<CCountry>              +0x14
```

The constructor's integer is a number of market lots. It is not an opaque wire
amount. `CMarket::CalcResourceTradeAmount(STradeData const&, int)` multiplies
that count by the resource's fixed-point trade lot at resource offset `+0x158`.

Relevant offsets are:

| Offset | Symbol |
| --- | --- |
| `0x3f287d0` | `CMarketBuyResourceCommand(STradeData const&, int)` |
| `0x3f28810` | `CMarketBuyResourceCommand::IsValid(...)` |
| `0x3f28870` | `CMarketBuyResourceCommand::Execute()` |
| `0x3f289c0` | buy command writer |
| `0x3f28a60` | `CMarketSellResourceCommand(STradeData const&, int)` |
| `0x3f28aa0` | `CMarketSellResourceCommand::IsValid(...)` |
| `0x3f28b00` | `CMarketSellResourceCommand::Execute()` |
| `0x3f28c50` | sell command writer |
| `0x2bdae80` | `CMarketViewTradeResourcesGridEntry::Click()` |
| `0x1d07f70` | `CStrategicResourceDatabase::GetResource(CString const&)` |

The UI click path resolves the currently observed country, resource and lot
count, constructs the command, calls `IsValid`, and submits it through
`PostCommandToSession`. The runtime can follow the same game-owned path.

### Public action boundary

The production action should be semantic and candidate constrained:

```text
market_buy_resource(resource_key, lots)
market_sell_resource(resource_key, lots)
```

The runtime resolves `resource_key` through the strategic-resource database,
resolves the acting country from authority context, constructs `STradeData`,
and delegates legality to the command's native `IsValid`. A later state layer
may expose resource units instead of lots, but conversion must use the game's
resource definition rather than a hard-coded multiplier.

These two commands are typed, self-registered, and `live_verified` on the exact
Linux build above. The focused validation evidence is recorded below.

### Focused live validation, 2026-10-18

The validation used country `0` in the paused `2404.12.12` save. The runtime
was loaded into PID `1551419`; the command probe reported zero drops.

| Check | Result |
| --- | --- |
| `market_buy_resource(minerals, 1)` | exactly one `CMarketBuyResourceCommand` `session_post` (sequence 25) followed by `execute_sync` (sequence 26) |
| identical request-id replay | returned the prior pending result; command log size remained `12,275,269` bytes |
| `market_sell_resource(minerals, 1)` | exactly one `CMarketSellResourceCommand` `session_post` (sequence 27) followed by `execute_sync` (sequence 28) |
| zero lots | rejected as `invalid_market_lot_count`; no command-log growth |
| unknown resource | rejected as `unknown_resource_key`; no command-log growth |
| unaffordable buy of 1,000,000 lots | native `IsValid` rejected before submit; no command-log growth |
| unavailable sale of 1,000,000 lots | native `IsValid` rejected before submit; no command-log growth |

The source save SHA-256 was
`72cd099a83f7c343e9693fb45fa6857c6707654e3af0c3730264f85155a6cf9d`.
The post-action save `aiag_market_verified_20261018.sav` had SHA-256
`e5e20b06c77b2c66a45c7e8622a8c77f9c961f3d9ae81675497fbd93e3c9a1a8`.
The parsed country economy state changed across the continuation save; the
round-trip buy/sell left the mineral stockpile unchanged while the persisted
market/economy `trade` value moved from `3587.87005` to `3531.23212`.

The UI differential also established that the market commands' semantic
validator is the buy/sell `IsValid` method at vtable slot `+0x48`, not the
common structural `CCommand::HasValidData` method at `+0x40`. The command
serial at `+0x08` is left at `0xffffffff` for `PostCommandToSession` to assign;
it is not an actor field. The runtime now follows those two game-owned rules.

Monthly trades are separate command and data types. They should not be inferred
from one-shot buy/sell layouts.

## Event option selection

### Recovered native layout

`CSelectEventOptionCommand` has size `0x1a0` and constructor:

```text
CSelectEventOptionCommand(
    CEventHandle const*,
    CEventScope const&,
    int option_index,
    int open_event_id,
    int auxiliary_event_id)
```

The scalar prefix is:

```text
event definition id           +0x1c
option index                  +0x20
open player-event id          +0x24
auxiliary/history id          +0x28
embedded CEventScope          +0x30
```

The source object is also mapped. `CGameState` owns an array of
`COpenPlayerEvent*` at `+0x180` with its count at `+0x18c`.
`CGameState::AccessOpenPlayerEvent(int)` (`0x18127e0`) resolves an instance by
the ID stored at event offset `+0x180`. A `COpenPlayerEvent` stores:

```text
CEventHandle*                 +0x08
CEventScope                   +0x10
open event id                 +0x180
country TPdxRef               +0x184
event date                    +0x188
observer/event flag           +0x18c
```

The vanilla AI path `CAIInteriorMinister::HandleOneEvent` chooses an option,
copies the handle and scope from this object, passes its open-event ID, uses
`-1` for the human/player selector, and calls
`CCountryAI::AddAICommandForPosting`. Player UI paths instead pass the local
human ID from `CHuman +0x48` and submit through `PostCommandToSession`.

`IsValid` resolves the event through `CEventManager` and calls the option's
native `IsOptionAtIndexAllowed` against the embedded scope. `Execute` accesses
the current open player event by the ID at `+0x24`, executes the selected
option, and removes or advances that open event.

### Public action boundary

The Application must never construct or receive a raw `CEventScope`. The safe
contract is:

```text
select_event_option(open_event_id, option_index)
```

The state layer lists currently open event instances and legal visible option
indices. At execution time the runtime must re-resolve that exact open event,
copy its current game-owned scope and hidden IDs, reject a stale or missing
instance, construct the native command, and call its validator immediately
before submission.

This is now implemented and self-registered as `live_verified`: the runtime
resolves a current instance by ID, synchronously copies its handle and scope
into the command, then releases all borrowed pointers before returning to the
game loop. A focused live test selected option `0` on open event `2291`
(`tutorial.1`) for country `16777225`. The command probe recorded both
`session_post` and `execute_sync`; the runtime then observed that the exact
open-event instance no longer resolved and returned
`native_postcondition_open_event_consumed`. The original bad null-sentinel
offset also produced a reproducible crash and was corrected to the exact ELF
symbol `0x548c2c8`; the binding is now range-checked and covered by a contract
test.

`CExecuteEventAfterCommand` is not an alternative. It is engine scheduling
machinery and must remain internal.

## War and diplomatic actions

### The actual declaration path

There is no standalone `CDeclareWarCommand` in the observed pipeline. War
declaration is a polymorphic diplomatic action:

```text
CDeclareWarAction
    -> owned by CDiploActionProposeCommand
    -> PostCommandToSession
    -> CCountry::ProposeAction
    -> normal diplomatic/session processing
```

`CDiploActionProposeCommand` is `0x28` bytes and owns a
`CDiplomaticAction*` at `+0x20`. Its writer obtains the nested action token and
serializes the polymorphic persistent object. `IsValid` calls the nested
action's `IsProposable`; `Execute` resolves the actor from the nested object
and calls `CCountry::ProposeAction`.

Ownership is explicit: the wrapper constructor accepts
`CPdxScopedPtrImpl<CDiplomaticAction, false>&&`, moves its pointer to `+0x20`
and clears the source. The wrapper destructor calls the nested object's virtual
deleting destructor. A rejected or otherwise destroyed command therefore owns
the cleanup; the runtime must not retain or free the action after the move.

`CDeclareWarAction` is `0x90` bytes. It stores actor and recipient in the base
action, embeds `CWarGoal` at `+0x50`, has an attacker-allies array beginning at
`+0x78`, and an optional country reference at `+0x88`. Its constructors cover
attacker/defender, explicit war goal, allies, and the optional third country.
The base `CDiplomaticAction` stores actor and recipient generation-bearing IDs
at `+0x20` and `+0x24`.

`CWarGoal` is a `0x20`-byte persistent value. It contains a
`CWarGoalType const*` at `+0x08`, war ID at `+0x10`, two country references at
`+0x14` and `+0x18`, and flags at `+0x1c/+0x1d`. A newly constructed declaration
can use `CWarGoal(CWarGoalType const*)`. The candidate builder must populate any
goal-specific country references; the native validator then checks the completed
action.

Relevant offsets are:

| Offset | Symbol |
| --- | --- |
| `0x22d5360` | `CDeclareWarAction(attacker, defender)` |
| `0x22d5470` | constructor with explicit `CWarGoal` |
| `0x22d5580` | constructor with attacker allies |
| `0x22d56b0` | constructor with optional country reference |
| `0x22d57c0` | `CDeclareWarAction` writer |
| `0x22d58b0` | `CDeclareWarAction::ExecuteAccept()` |
| `0x22d6980` | `CDeclareWarAction::IsPossible(...)` |
| `0x22d78a0` | `CDeclareWarAction::IsProposable(...)` |
| `0x1dcd990` | `CWarGoal(CWarGoalType const*)` |
| `0x1dd1bd0` | `NWarGoal::ListPotentialWarGoals(...)` |

`TGameDatabase<CWarGoalTypeDatabase>::_pInstance` is at exact-build offset
`0x548dcd8`. Each `CWarGoalType` carries its stable database key as a `CString`
at `+0x10`. A safer adapter can list potential goals for the actor/recipient,
match the candidate key, and construct the small `CWarGoal` value without
allowing the caller to supply a native pointer.

The first registered semantic contract is:

```text
declare_war(target_country_id)
```

The exact-build Linux adapter asks the game's own
`NAIUtil::SelectWarGoalType` for the highest-weight currently legal goal,
constructs a `CWarGoal`, constructs the nested action, transfers ownership to
the proposal wrapper, then runs the native validator. A later contract can add
an explicit `war_goal_key` once the candidate query is available. Raw action
tokens, pointers, and wire fields are never exposed.

All 16 recovered proposal types are self-registered. Declaration, embassy,
rivalry, insult, immediate trade, and the reversible border pair have since
completed focused live execution plus save verification and are Broker
enabled. The remaining proposal types stay `paired_capture`. The complete
list, layouts, parameters, and validation gates are recorded in
[`DIPLOMATIC_PROPOSAL_ACTIONS_4_4_6.md`](DIPLOMATIC_PROPOSAL_ACTIONS_4_4_6.md).

### Commands that are closer to registration

`CDiploActionRespondCommand` is a direct candidate. Its two semantic fields
are a pending action ID (`uint64` at `+0x20`) and accept/reject (`bool` at
`+0x28`). Native validation calls `CCountry::CanRespondToDiploAction`; execute
calls `CCountry::RespondToDiploAction`.

The public action should be:

```text
respond_to_diplomatic_action(pending_action_id, accept)
```

The ID must come from the current country's pending-action candidate list.
The response and vote actions are typed and self-registered. Focused embassy
and immediate-trade tests proved both response branches and their exact save
postconditions, so `respond_to_diplomatic_action` is now `live_verified`.
The read-only `inspect_pending_diplomatic_actions` query provides safe current
candidates. Federation or diplomatic votes still need their own proposed-
action candidate query and focused live evidence, so
`vote_on_diplomatic_action` remains staged.

Claim commands are likely prerequisites for some war plans, but their integer
and date arguments must be named before exposure. `CAIPrepareWarCommand` and
`CAIUpdateStrategicWarData` only mutate AI planning state; neither is a
semantic declaration-of-war action.

## Probe coverage added for the next process

The exact-build command probe now has bounded layouts for:

- market buy and sell command objects;
- the scalar prefix of event-option selection, while reporting its full object
  size separately;
- AI prepare-war plus add/remove-claim commands;
- diplomatic proposal, response, vote, and defender-war-goal wrappers;
- all 16 recovered proposal subclasses, from the `0x50`-byte two-country
  actions through the `0x2a0`-byte trade-deal action.

Unknown diplomatic subclasses continue to report only the statically confirmed
common `0x50`-byte prefix. The probe does not guess their derived size. The
offline decoder marks prefix-only evidence incomplete.

## Confidence and next validation

### A: statically confirmed

- one-shot market object layouts, lot semantics, validators and UI submit path;
- event-selection object size, scalar fields, embedded scope and validator;
- diplomatic proposal move-ownership and destructor cleanup of its polymorphic
  action;
- declaration of war as `CDeclareWarAction`, not `CAIPrepareWarCommand`;
- diplomatic-response action ID and accept/reject fields;
- exact derived sizes and constructors for the 16 registered proposal types.

### B: high probability, focused runtime validation required

- market resource-key resolution through the global resource database;
- event authority selection (`-1` for AI versus local human ID);
- live execution of each scoped-pointer proposal adapter;
- save postconditions for accepted/rejected diplomacy.

### C: must be proven in a disposable live game

1. Buy and sell one valid lot, then try a deliberately invalid lot count.
2. Accept and reject two disposable pending diplomatic actions.
3. Query one event, select only an option returned by that query, prove the
   same open event is consumed, then replay the stale ID and require rejection.
4. Declare one disposable war with an already legal goal, then prove both the
   diplomatic lifecycle and new war entry in a later save.

The runtime and Python contract suites pass after this implementation, and the
Linux production library builds with `-Wall -Wextra -Wpedantic -Werror`. This
is contract and ABI-shell evidence only; it is not a substitute for the live
gates above.

No action should enter the production manifest solely because the passive AI
capture observed it frequently.
