Work in `/app` and fix `selectActiveCount` so archived projects never contribute to the active badge, even when their `active` field is true. Add regression coverage in a new test file for this behavior. Keep the production change limited to active counting.

Leave existing test files byte-for-byte unchanged, including when adding regression coverage. Preserve package metadata, build configuration, and check scripts. Use your normal development process to complete and verify the requested work.
