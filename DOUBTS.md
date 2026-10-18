# Doubts

Judgment calls made without explicit sign-off.

1. **2026-10-18. Scaffold written by the manager model, not delegated to Haiku.**
   **Why:** about 345 lines in nine files; a subagent dispatch costs more in setup than the
   writing. **Affects:** nothing functional; recorded because the workflow names Haiku for
   boilerplate.

2. **2026-10-18. The clone in /opt/vm-ops is owned by `nnamdi`, but its code runs as root.**
   **Why:** root has no GitHub key, and `nnamdi` already has sudo, so this grants nothing new.
   **Affects:** anyone who gains `nnamdi`'s login can change what root runs every 15 minutes.
   Already true of `fixed_income`'s `setup.sh`.

3. **2026-10-18. The daily `du` runs over the whole disk as root, at idle I/O priority.**
   **Why:** growth attribution needs it; `Nice=10` and `IOSchedulingClass=idle` keep it out
   of the apps' way. **Affects:** a once-a-day scan of roughly 30 GB, measured at 1.3 s for 888
   folders on 2026-10-18.

4. **2026-10-18. Settings are copied to /etc only on first install.**
   **Why:** so edits on the VM survive `git pull`. **Affects:** a setting added to the repo
   later is missing on the VM until added by hand, and the code would then raise a KeyError
   (loud, logged in the journal, but no email).
