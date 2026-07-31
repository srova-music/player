## Summary

Describe the change and the user-visible outcome.

## Scope

List the files or components intentionally changed.

## Validation

- [ ] Modified Python files pass syntax checks
- [ ] Modified shell scripts pass `bash -n`
- [ ] Relevant automated tests pass
- [ ] Desktop browser behaviour checked where applicable
- [ ] Tablet/mobile behaviour checked where applicable
- [ ] Local Music, TIDAL, Radio, Queue, and player-bar impact considered
- [ ] No credentials, runtime data, databases, logs, or machine-specific paths added

## Audio and packaging

Complete when relevant:

- [ ] Bit-perfect and exclusive ALSA behaviour preserved
- [ ] Architecture-specific Rust library verified
- [ ] AMD64 package built and checked
- [ ] ARM64 package built and checked
- [ ] Package installation/live playback tested by the user

## Browser assets

- [ ] Cache-busting reference updated when browser assets changed
- [ ] Screenshots attached for visible UI changes

## Rollback

Describe the rollback point or backup relevant to this change.

## Notes

Include known limitations, deferred work, or follow-up items.
