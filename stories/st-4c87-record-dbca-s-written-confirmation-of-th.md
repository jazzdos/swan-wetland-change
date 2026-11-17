---
id: st-4c87
title: Record DBCA's written confirmation of the DBCA-010 licence
type: chore
priority: P2
depends_on: []
discovered_from: st-22f1
touches: [docs/research]
exclusive: false
created: 2026-11-15
updated: 2026-11-17
parked_complexity: routine
---

## Description

DBCA-010 Ramsar Sites is published under CC BY-NC 4.0, the licence on the custodian's catalogue entry (catalogue.data.wa.gov.au, fetched 2026-11-14), adopted 2026-11-15 on the orchestrator's recommendation and not confirmed in writing by DBCA (docs/research/2026-11-14-public-release-licences.md, data/SOURCES.md, src/wetland_change/dbca_attribution.py DBCA_LICENCE_BASIS). ADR 0016 precondition 3 recommends DBCA's written confirmation that CC BY-NC 4.0 applies to public redistribution of DBCA-010 and of derived products before the public-read apply. On 2026-11-15 Jarrod parked that confirmation and approved continuing to the apply without it ('approved tofu plan and park written confirmation from dbca - contineu without it'). Asking DBCA is a human action (an email or request to the custodian), so this story waits on Jarrod.

## Acceptance Criteria

- [ ] A dated record of DBCA's written reply on the DBCA-010 licence is committed under docs/research
- [ ] If DBCA confirms CC BY-NC 4.0
- [ ] data/SOURCES.md and DBCA_LICENCE_BASIS cite the reply instead of 'not confirmed in writing by DBCA'
- [ ] with their tests updated
- [ ] If DBCA states another licence or bars redistribution
- [ ] a story is filed to change the published licence and access before anything else is published

## Implementation Plan

## Implementation Notes

- 2026-11-17T11:19:24.558Z: 2026-11-17: Shelved to backlog. Jarrod: "just make it password protected so its not public - im not contacting dbca". The output bucket returns to private under st-90b4 (ADR 0017), so DBCA's written confirmation for public redistribution is no longer sought.

## Questions

- 2026-11-15T11:36:27.495Z: Has DBCA confirmed in writing that CC BY-NC 4.0 applies to public redistribution of DBCA-010 and of products derived from it? Jarrod parked this on 2026-11-15 and approved the public-read apply without it (ADR 0016 precondition 3 waived). Resume when a reply arrives: record it under docs/research and update data/SOURCES.md and DBCA_LICENCE_BASIS, or file a licence change story if DBCA states otherwise.
