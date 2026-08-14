# Tree-sitter grammar bake cache (offline)

Optional offline seed for runtime / ast-indexer images (~29MB for the 7
languages used by `chunking._EXT_TO_TS_LANG`).

`tree-sitter-language-pack` ≥1.14 downloads compiled grammars from GitHub
Releases on first `get_parser()`. Behind a bad path that can GIL-block forever,
so Dockerfiles bake grammars at **image build** via
`services/runtime/scripts/bake_ts_grammars.py`.

## Layout

```text
deploy/ts-grammar-cache/
  v1.14.3/
    libs/
      libtree_sitter_python.so
      …
    manifest.json
    bundles/…
```

Empty (README only) → build runs `prefetch()` (needs network). Network miss is a
warning by default (`TS_GRAMMAR_BAKE_REQUIRED=1` to fail the build).

## Refresh

```bash
docker cp services/runtime/scripts/bake_ts_grammars.py agent-runtime:/tmp/bake_ts_grammars.py
docker exec -u app -e HOME=/home/app agent-runtime python -u /tmp/bake_ts_grammars.py
docker cp agent-runtime:/home/app/.cache/tree-sitter-language-pack/. \
  deploy/ts-grammar-cache/
```

Rebuild path: `make up-runtime` / `make up-ast-indexer` (same
`Dockerfile.retrieval`) copies this seed into the image.
