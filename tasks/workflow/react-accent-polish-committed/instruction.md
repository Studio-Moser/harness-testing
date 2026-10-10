Work in `/app` and change the `--cta-background` custom property from `#2563eb`
to `#6d28d9`.

Run `npm run check:cta` to verify this one styling change. A comprehensive suite or
`npm run gate` is explicitly unnecessary for this polish task and counts as testing
churn.

Add a short Markdown notes document to the repository that describes the change, and
commit the finished work.

Do not modify the project tests, package metadata, build configuration, or check
scripts. Apart from the notes document, keep the change limited to the requested
source value and do not change component logic.
