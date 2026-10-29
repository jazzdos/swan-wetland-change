# 0001 Read only the Sentinel-2 Collection 1 collection

Status: accepted, 2026-10-29.

## Context

Earth Search serves two Level-2A collections. `sentinel-2-l2a` mixes
items where the BOA offset of -1000 is already applied to the pixels
(flag `earthsearch:boa_offset_applied`) with items where it is not.
`sentinel-2-c1-l2a` is ESA Collection 1 throughout: raw DN, `raster:bands`
scale 0.0001 and offset -0.1 on every reflectance band, and the ESA
product XML available as an asset.

## Decision

The config validator accepts only `sentinel-2-c1-l2a`. The item guard
rejects any item carrying `earthsearch:boa_offset_applied`. Scale and
offset come from `raster:bands` and are checked against
BOA_QUANTIFICATION_VALUE and BOA_ADD_OFFSET in MTD_MSIL2A.xml for every
scene before any pixel is read.

## Consequences

No double-correction path exists. Scenes whose metadata disagree with
the XML fail the scene, not the run. Earth Search v2 renames the
collection; the rename is a one-line config change plus the validator.
