# Rebookr v1 (legacy) - "it worked in the demo"

This is how Rebookr looked when we inherited it. Count the problems:

- The Anthropic SDK is imported in every file.
- Model names are hard-coded in four places.
- `resp.content[0].text` assumes Anthropic's response shape everywhere.
- Tool schemas use Anthropic's `input_schema` format inline.
- No timeout, no fallback, no error handling. One provider down = whole product down.

Run it (control tower must be running):

    python -m legacy.storm
