# Story Lab

Additive long-form film, TV and anime analysis subsystem for OpenShorts.

Current vertical slice: independent project persistence under output/storylab, transcript analysis through the existing optional text-only LLM backend, evidence/theory contracts with timestamp safety, documentary script outline generation, and an isolated ffmpeg scene extraction primitive.

The subsystem does not mutate Shorts job state. Media ingestion, evidence browser, full 16:9 composition and teaser generation are deliberately staged after local integration tests establish source/media conventions.
