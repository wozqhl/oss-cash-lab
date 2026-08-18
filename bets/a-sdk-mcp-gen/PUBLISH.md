# Publish notes


Official docs: https://modelcontextprotocol.io/registry/quickstart
Registry host: https://registry.modelcontextprotocol.io (metadata only).

This package is the OpenAPI-to-SDK-and-MCP generator CLI (bin sdk-mcp-gen).
It is not a stdio MCP server. Official registry listing is for servers.
So package.json does not set mcpName, and this directory has no live server.json.
Putting those on the generator would claim the CLI speaks MCP; it does not.

Intended registry name if a human later lists a generated server: io.github.wozqhl/sdk-mcp-gen
(GitHub-auth namespace io.github.wozqhl/ per the official quickstart).

## Generated-example (petstore MCP)

The CLI writes the actual MCP server next to the SDK. Look at:

- out/petstore/mcp-server.mjs -- Node stdio MCP
- out/petstore/mcp_server.py and mcp_server.go -- same tools
- out/petstore/mcp.json -- paste-ready client snippet
- out/petstore/mcp-tools.json -- tool names (listPets, createPet, getPet, deletePet)

That tree is what you would wrap for the MCP Registry, not this generator package.

Reproduce: node src/cli.js generate examples/petstore.openapi.json --out out/petstore

## 1. Pack the generator

From bets/a-sdk-mcp-gen (or a future standalone repo):

    npm pack
    tar tzf oss-cash-lab-sdk-mcp-gen-0.1.0.tgz

Inspect the tarball. Do not upload the package from CI or agents.
`npm pack` is the local proof; publish is still manual.
The files field includes src/, examples/, action.yml, and docs.
The bin field already points at ./src/cli.js. Engines: Node >=18.
If LICENSE/NOTICE are missing here, copy them from the portfolio root first.
The scoped name needs an org or a rename (human decision).

## 2. Official registry publisher (generated server, not this CLI)

Per the official quickstart:

1. Wrap the generated server as its own package whose start command is the stdio server
   (for petstore: node mcp-server.mjs), not this generator CLI.
2. Set mcpName on THAT package to io.github.wozqhl/sdk-mcp-gen (must match server.json name).
3. Upload that wrapper to the public JS package registry first (registry verifies mcpName).
4. Install the official publisher CLI, init, edit server.json, login via GitHub, then upload.

Example server.json for a generated petstore-style server (do not drop this on the generator package):


```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.wozqhl/sdk-mcp-gen",
  "description": "Stdio MCP server from an OpenAPI spec (petstore fixture example).",
  "version": "0.1.0",
  "repository": { "url": "https://github.com/wozqhl/oss-cash-lab", "source": "github" },
  "packages": [
    {
      "registryType": "npm",
      "identifier": "@oss-cash-lab/petstore-mcp",
      "version": "0.1.0",
      "transport": { "type": "stdio" }
    }
  ]
}
```

identifier must be the package that IS the server. @oss-cash-lab/petstore-mcp is a placeholder, not uploaded.

Install the official publisher CLI from the modelcontextprotocol/registry releases (pin a release in real use). Then a human may:

    mcp-publisher init
    # edit server.json so name == package.json mcpName == io.github.wozqhl/sdk-mcp-gen
    mcp-publisher login github
    # mcp-publisher publish   # do not run here

This repo is not listed. Do not invent a listing.

## GitHub Action

Consumers can run the composite Action without uploading any package:

    uses: wozqhl/oss-cash-lab/bets/a-sdk-mcp-gen@main
    with:
      spec: examples/petstore.openapi.json
      output: sdk

See action.yml and examples/github-actions/sdk-mcp-gen-generate.yml.
