# Species Rights Negative Validation (Stellaris 4.4.6)

> Publication: original/local evidence paths below are provenance labels, not Git downloads. Use the [indexed archive and access status](../research/EVIDENCE_ARCHIVE.md); public copies may be privacy-redacted and originals remain retained.


## Historical negative result

The original `species 83 <- species 2` experiment was correctly kept at
`paired_capture` at the time.

The current adapters passed native validation and produced continuation saves
(`species_rights_83_from_2.sav` and `species_default_from_2.sav`), but the
intended current rights did not change. Only `former_*` state moved. That is
not the semantic postcondition advertised by either action.

This result is useful negative evidence: the native constructor and submitted
object are structurally plausible, but the current template-copy contract is
not yet sufficient. Production must not infer success from `session_post`, a
save write, or mutation of historical fields. Before promotion, the nested
rights object and template semantics must be recovered and every requested
current-rights field compared before and after on a disposable save.

## Superseding focused validation

The follow-up used explicit, currently legal rights configurations owned by
country `0`. `set_species_rights(20, 29)` changed all differing current fields
for species `20` from normal/limited/none to the template's
tech-assimilation/assimilation/limited configuration. The continuation save is
`species_rights_country0_20_from29_retry.sav`, SHA-256
`e4dde8ff6cd94c96f303014bf071e5af6ae09a507a04ad532ba19a3016cf92e5`.

`set_default_species_rights(31)` then changed the default configuration from
tech-assimilation/assimilation/limited to species `31`'s
normal/limited/none configuration. The save also records the exact former
values and the expected `2416.09.01` cooldown dates. Its evidence save is
`species_default_country0_from31.sav`, SHA-256
`f1edf5a39d34a86118403fc38a24169ffe10df38e73a2e50ef7d4071af7446fa`.

An attempted primary-species template on country `50331717` was rejected with
`template_species_rights_configuration_unavailable`, providing a bounded
negative result instead of silently posting an invalid configuration. These
focused positive and negative cases supersede the earlier inconclusive pair;
both exact-build descriptors are now `live_verified`.
