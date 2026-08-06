# KUMA800

**KUMA800** is an experimental MCP server for turning official bear-sighting open data into traceable, locally usable safety information for AI agents and humans.

The initial target is **Yamagata Prefecture, Japan**.

> Safety infrastructure should not erase uncertain information. It should carry source, freshness, location, and uncertainty to the user.

## Status

**Season 0: architecture and implementation planning**

KUMA800 is currently in the design phase. The runtime, language, MCP SDK, storage strategy, update mechanism, geospatial model, and security boundaries have not yet been finalized.

No production safety guarantee is provided at this stage.

## Why KUMA800 exists

Official bear-sighting information exists, but it is fragmented across municipal websites, PDFs, KML/KMZ files, map platforms, and public applications.

General-purpose AI can also confuse two different kinds of caution:

- caution about legal or political claims;
- caution about immediate physical danger.

When physical-risk data is hidden, weakened, or discarded merely because it is local, incomplete, or sensitive, the system may become less safe rather than more safe.

KUMA800 aims to provide a small, inspectable, open-source bridge between official data and user-controlled AI agents.

## Current confirmed source shape

A currently confirmed Yamagata dataset is published through Google My Maps in two layers:

1. **Symbolic KML**
   - contains a KML `NetworkLink`;
   - points to a public Google My Maps KML endpoint;
   - contains no sighting `Placemark` records itself.

2. **KMZ payload**
   - contains the materialized map data;
   - includes `doc.kml` and map icon assets;
   - the inspected R7 sample contains 3,092 `Placemark` elements.

Current symbolic endpoint discovered from the supplied official KML:

```text
https://www.google.com/maps/d/kml?forcekml=1&mid=1N9E9rixBQwxB4TKQ2XsP32GLOi6w6qQ
```

This repository does not treat the Google platform, the link target, the downloaded archive, or the parsed records as implicitly trusted.

## Zero-trust interpretation

For KUMA800, “zero trust” does not mean refusing to use public data. It means verifying every boundary.

The Season 1 fetch pipeline should, at minimum:

1. load the known symbolic KML;
2. parse the `NetworkLink` without executing arbitrary XML features;
3. validate the URL scheme and expected host policy;
4. fetch with explicit timeout, size, redirect, and content-type limits;
5. preserve retrieval time, final URL, headers, and content hash;
6. verify that the result is a valid KML or KMZ container;
7. reject path traversal, decompression bombs, malformed XML, and external entity expansion;
8. parse records into a normalized internal schema;
9. keep the original source reference and raw evidence linkage;
10. report stale, missing, ambiguous, or partially parsed data instead of converting absence into safety.

## Roadmap

### Season 0: Forge the architecture

Goal: decide the technical stack and implementation policy before declaring a stable interface.

Topics under evaluation:

- implementation language and supported runtimes;
- official MCP SDK and transport choice;
- local-only execution versus optional remote components;
- KML/KMZ and geospatial parsing libraries;
- normalized event schema;
- cache, snapshot, and provenance storage;
- update polling and diff strategy;
- source allow-list and redirect policy;
- XML, archive, and decompression hardening;
- offline behavior;
- privacy modes for public facilities and private residences;
- test fixtures and reproducible source snapshots;
- risk-ranking boundaries and non-goals.

Season 0 deliverables:

- [ ] architecture decision records;
- [ ] threat model;
- [ ] source and record schema;
- [ ] MCP tool draft;
- [ ] minimal parser spike for the supplied symbolic KML and KMZ;
- [ ] fixture policy that respects upstream data terms;
- [ ] Season 1 acceptance tests.

### Season 1: Current Yamagata open data

Goal: allow a user-controlled local MCP server to retrieve current official Yamagata bear-sighting open data through a zero-trust pipeline.

Minimum current requirement:

- accept or fetch the known symbolic KML;
- resolve its Google My Maps `NetworkLink` under an explicit policy;
- retrieve and validate the materialized KML/KMZ data;
- expose traceable sighting records through MCP.

Candidate MCP tools:

- `kuma.sources.list`
- `kuma.source.inspect`
- `kuma.sightings.search`
- `kuma.sightings.nearby`
- `kuma.data.freshness`
- `kuma.data.quality`

Season 1 acceptance direction:

- [ ] every returned record can be traced to a source;
- [ ] retrieval and observation times are not conflated;
- [ ] malformed or unexpected payloads fail closed without erasing the last known valid snapshot;
- [ ] no sighting result is never represented as proof that no bear exists;
- [ ] the server runs on infrastructure controlled by the user;
- [ ] no mandatory proprietary AI or hosted database dependency.

### Season 2: Multi-year history

Goal: make multiple years of official historical records queryable from open data.

Planned work:

- source adapters for annual datasets;
- cross-year schema normalization;
- duplicate and correction handling;
- snapshot provenance and hashes;
- time-range and year-based MCP queries;
- explicit handling of boundary, field, and reporting-rule changes;
- comparison tools that distinguish raw counts from changes in collection practice.

Possible tools:

- `kuma.history.search`
- `kuma.history.compare`
- `kuma.source.revisions`

### Season 3: Other prefectures

Goal: expand beyond Yamagata without forcing every prefecture into a false single format.

The likely architecture is a shared core plus prefecture or municipality adapters:

```text
KUMA800 Core
├── normalized schema
├── provenance and validation
├── MCP tools
└── source adapters
    ├── yamagata
    ├── miyagi
    ├── fukushima
    └── ...
```

Season 3 should preserve regional differences while exposing a common minimum interface. A future generic package may evolve into a broader `jp-wildlife-mcp`, but that is not a Season 1 requirement.

## Tentative record model

The internal record model may include:

```text
source_id
source_url
publisher
retrieved_at
published_at
observed_at
location_text
latitude
longitude
geometry_precision
observation_type
animal_count
raw_description
source_record_id
content_hash
parse_confidence
```

The schema remains provisional during Season 0.

## Non-goals

KUMA800 is not intended to:

- guarantee that an area is bear-free;
- replace emergency services, municipalities, wildlife specialists, or field judgment;
- identify or track individual animals without a reliable official basis;
- issue autonomous capture or confrontation instructions;
- hide official location data merely because it is geographically precise;
- publish private-residence information without an appropriate privacy policy;
- convert legal disclaimers into a reason to suppress physical-risk evidence.

## Data and licensing boundary

The **KUMA800 source code** is licensed under the Apache License 2.0.

Upstream government data, Google My Maps content, KML/KMZ files, map imagery, icons, and third-party datasets retain their own terms and attribution requirements. Apache-2.0 for this repository does not relicense upstream data.

Before redistributing fixtures or snapshots, confirm the applicable source terms. Tests may use minimized, synthetic, hashed, or metadata-only fixtures where full redistribution is not appropriate.

## Security

KML and KMZ are untrusted input formats.

Relevant threats include:

- XML external entities;
- entity expansion;
- archive path traversal;
- decompression bombs;
- oversized coordinates or descriptions;
- unexpected redirects;
- stale or silently replaced map resources;
- schema drift;
- duplicate or corrected observations;
- maliciously crafted local files.

Security decisions and parser limits will be documented during Season 0.

## Contributing

The project is currently collecting architecture proposals, source discoveries, parser experiments, threat-model notes, and implementation candidates.

Useful contributions include:

- verified official source URLs;
- sample schemas and field mappings;
- safe KML/KMZ parser evaluations;
- MCP SDK comparisons;
- geospatial indexing experiments;
- reproducible failure cases;
- accessibility and offline-use requirements.

Please keep claims traceable. Separate confirmed behavior, inference, and proposal.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).

---

KUMA800 begins with Yamagata, a symbolic KML, and one stubborn requirement: **do not let an AI burn the map that protects the user’s HP and Life.**
