Repair the FAQ disclosure so mouse and keyboard users get the same state.

Click, Enter, and Space must toggle the answer while keeping the trigger's
`aria-expanded` value and the panel's `hidden` state synchronized.

Run `npm test -- test/Disclosure.test.js` for the focused behavior, then run `npm test`
once as the final package check.
