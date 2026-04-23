# LeagueBrief FantasyPros Adapter

Standalone parser for packaged FantasyPros ADP CSV files.

The adapter discovers files named
`FantasyPros_{year}_Overall_ADP_Rankings-{STD|HALF|PPR}.csv`, maps scoring from
the suffix, repairs known apostrophe-split CSV rows, and parses ADP rows without
depending on legacy prototype code.

Player matching exports a normalized name for downstream SQL ingestion. The
normalizer lowercases, strips accents and punctuation, removes suffix tokens
such as `Jr.`, `II`, and `III`, and collapses whitespace. LeagueBrief matches on
normalized name plus base position, while team remains row-level metadata.
