#!/usr/bin/env node
'use strict';

const fs = require('fs');

// ── Extract the JSON from the HTML ──────────────────────────────────────────
const html = fs.readFileSync(
  '/Users/stefanhiekin/projects/fl_ag_campaign_site/campaign_schedule_outreach.html',
  'utf8'
);

const match = html.match(/window\.FL_AG_CAMPAIGN_DATA\s*=\s*(\[[\s\S]*?\]);\s*\n/);
if (!match) {
  // Try a greedier match if the first fails
  const m2 = html.match(/window\.FL_AG_CAMPAIGN_DATA\s*=\s*(\[[\s\S]*\])\s*;/);
  if (!m2) { console.error('Could not find FL_AG_CAMPAIGN_DATA'); process.exit(1); }
  var jsonStr = m2[1];
} else {
  var jsonStr = match[1];
}

let data;
try {
  data = JSON.parse(jsonStr);
} catch(e) {
  console.error('JSON parse error:', e.message);
  process.exit(1);
}

console.log(`Loaded ${data.length} records.\n`);

// ── Helpers ──────────────────────────────────────────────────────────────────
const isEmpty = v => v === null || v === undefined || (typeof v === 'string' && v.trim() === '');
const name = r => r['Organization_or_Event_Name'] || '(no name)';

// ════════════════════════════════════════════════════════════════════════════
// CHECK 1 — Completeness Audit
// ════════════════════════════════════════════════════════════════════════════
console.log('═'.repeat(70));
console.log('CHECK 1 — COMPLETENESS AUDIT');
console.log('═'.repeat(70));

const REQUIRED_FIELDS = [
  'Region',
  'County',
  'Category',
  'Subcategory',
  'Organization_or_Event_Name',
  'Contact_Name',
  'Website',
  'Source_URL',
];

const check1Issues = [];
data.forEach((rec, idx) => {
  REQUIRED_FIELDS.forEach(field => {
    if (isEmpty(rec[field])) {
      check1Issues.push({ idx, org: name(rec), field });
    }
  });
});

if (check1Issues.length === 0) {
  console.log('✓ No missing required fields found.\n');
} else {
  console.log(`Found ${check1Issues.length} blank required field(s):\n`);
  // Group by field for cleaner output
  const byField = {};
  check1Issues.forEach(({ idx, org, field }) => {
    if (!byField[field]) byField[field] = [];
    byField[field].push({ idx, org });
  });
  Object.entries(byField).forEach(([field, records]) => {
    console.log(`  Field: ${field} — ${records.length} blank(s)`);
    records.forEach(({ idx, org }) => {
      console.log(`    [${idx}] ${org}`);
    });
  });
  console.log();
}

// Summary counts per field
console.log('Blank count per required field:');
REQUIRED_FIELDS.forEach(field => {
  const count = data.filter(r => isEmpty(r[field])).length;
  console.log(`  ${field.padEnd(35)} ${count}`);
});
console.log();

// ════════════════════════════════════════════════════════════════════════════
// CHECK 4 — Date Validation
// ════════════════════════════════════════════════════════════════════════════
console.log('═'.repeat(70));
console.log('CHECK 4 — DATE VALIDATION');
console.log('═'.repeat(70));

const MONTH_NAMES = ['January','February','March','April','May','June',
                     'July','August','September','October','November','December'];
const DATE_REGEX = /^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$/;

const tbdRecords = [];
const badFormat = [];
const beforeApril2026 = [];
const outsideWindow = [];
const monthCounts = {};

data.forEach((rec, idx) => {
  const d = rec['Meeting_or_Event_Date'];
  if (isEmpty(d)) {
    tbdRecords.push({ idx, org: name(rec) });
    return;
  }
  const m = d.trim().match(DATE_REGEX);
  if (!m) {
    badFormat.push({ idx, org: name(rec), value: d });
    return;
  }
  const [, monthStr, dayStr, yearStr] = m;
  const monthIdx = MONTH_NAMES.findIndex(mn => mn.toLowerCase() === monthStr.toLowerCase());
  const year = parseInt(yearStr, 10);
  const month = monthIdx + 1; // 1-based

  if (monthIdx === -1) {
    badFormat.push({ idx, org: name(rec), value: d, reason: 'unknown month name' });
    return;
  }

  // Track distribution
  const key = `${monthStr} ${year}`;
  monthCounts[key] = (monthCounts[key] || 0) + 1;

  // Check before April 2026
  if (year < 2026 || (year === 2026 && month < 4)) {
    beforeApril2026.push({ idx, org: name(rec), value: d });
  }

  // Check outside April–August 2026 window
  if (year !== 2026 || month < 4 || month > 8) {
    outsideWindow.push({ idx, org: name(rec), value: d });
  }
});

// Bad format
if (badFormat.length === 0) {
  console.log('✓ All dated records match "Month D, YYYY" format.\n');
} else {
  console.log(`Bad date format — ${badFormat.length} record(s):`);
  badFormat.forEach(({ idx, org, value }) => console.log(`  [${idx}] ${org} → "${value}"`));
  console.log();
}

// Before April 2026
if (beforeApril2026.length === 0) {
  console.log('✓ No dates before April 2026.\n');
} else {
  console.log(`Dates BEFORE April 2026 — ${beforeApril2026.length} record(s):`);
  beforeApril2026.forEach(({ idx, org, value }) => console.log(`  [${idx}] ${org} → "${value}"`));
  console.log();
}

// Outside April–August 2026
if (outsideWindow.length === 0) {
  console.log('✓ All dates fall within April–August 2026 window.\n');
} else {
  console.log(`Dates OUTSIDE April–August 2026 window — ${outsideWindow.length} record(s):`);
  outsideWindow.forEach(({ idx, org, value }) => console.log(`  [${idx}] ${org} → "${value}"`));
  console.log();
}

// Month distribution
console.log('Month distribution (records with a date):');
// Sort by year then month
const sortedMonths = Object.entries(monthCounts).sort(([a], [b]) => {
  const [am, ay] = a.split(' '); const [bm, by] = b.split(' ');
  const ai = MONTH_NAMES.indexOf(am); const bi = MONTH_NAMES.indexOf(bm);
  return parseInt(ay) - parseInt(by) || ai - bi;
});
sortedMonths.forEach(([k, v]) => console.log(`  ${k.padEnd(20)} ${v}`));
console.log();

// TBD records
console.log(`TBD records (no date) — ${tbdRecords.length} total:`);
if (tbdRecords.length > 0) {
  tbdRecords.forEach(({ idx, org }) => console.log(`  [${idx}] ${org}`));
}
console.log();

// ════════════════════════════════════════════════════════════════════════════
// CHECK 5 — County / Region Validation
// ════════════════════════════════════════════════════════════════════════════
console.log('═'.repeat(70));
console.log('CHECK 5 — COUNTY / REGION VALIDATION');
console.log('═'.repeat(70));

const OFFICIAL_COUNTIES = new Set([
  'Alachua','Baker','Bay','Bradford','Brevard','Broward','Calhoun','Charlotte',
  'Citrus','Clay','Collier','Columbia','DeSoto','Dixie','Duval','Escambia',
  'Flagler','Franklin','Gadsden','Gilchrist','Glades','Gulf','Hamilton','Hardee',
  'Hendry','Hernando','Highlands','Hillsborough','Holmes','Indian River','Jackson',
  'Jefferson','Lafayette','Lake','Lee','Leon','Levy','Liberty','Madison','Manatee',
  'Marion','Martin','Miami-Dade','Monroe','Nassau','Okaloosa','Okeechobee','Orange',
  'Osceola','Palm Beach','Pasco','Pinellas','Polk','Putnam','Santa Rosa','Sarasota',
  'Seminole','St. Johns','St. Lucie','Sumter','Suwannee','Taylor','Union','Volusia',
  'Wakulla','Walton','Washington'
]);

// Known region→county mappings to verify
const KNOWN_MAPPINGS = {
  'Miami-Dade':   'South Florida',
  'Duval':        'Northeast Florida',
  'Hillsborough': 'Central Florida',
  'Escambia':     'Northwest Florida',
  'Leon':         'North Central Florida',
  'Orange':       'Central Florida',
  'Polk':         'Central Florida',
  'Palm Beach':   'South Florida',
  'Broward':      'South Florida',
  'Lee':          'Southwest Florida',
  'Collier':      'Southwest Florida',
  'Volusia':      'Northeast Florida',
  'Brevard':      'Central Florida',
  'Pinellas':     'Central Florida',
};

// Collect unique counties and their region(s)
const countyRegionMap = {}; // county → Set<region>
const regionCountyMap = {}; // region → Set<county>

data.forEach((rec, idx) => {
  const county = rec['County'];
  const region = rec['Region'];
  if (!isEmpty(county)) {
    if (!countyRegionMap[county]) countyRegionMap[county] = new Set();
    countyRegionMap[county].add(region || '(blank)');
  }
  if (!isEmpty(region)) {
    if (!regionCountyMap[region]) regionCountyMap[region] = new Set();
    regionCountyMap[region].add(county || '(blank)');
  }
});

const uniqueCounties = Object.keys(countyRegionMap).sort();
console.log(`Unique counties in data (${uniqueCounties.length}):`);
console.log('  ' + uniqueCounties.join(', ') + '\n');

// Invalid counties
const invalidCounties = uniqueCounties.filter(c => !OFFICIAL_COUNTIES.has(c));
if (invalidCounties.length === 0) {
  console.log('✓ All county names match the official Florida county list.\n');
} else {
  console.log(`Invalid/unrecognised counties — ${invalidCounties.length}:`);
  invalidCounties.forEach(c => console.log(`  "${c}" → found in regions: ${[...countyRegionMap[c]].join(', ')}`));
  console.log();
}

// Missing counties (in official list but not in data)
const missingCounties = [...OFFICIAL_COUNTIES].filter(c => !countyRegionMap[c]).sort();
console.log(`Counties in official list but NOT in data (${missingCounties.length}):`);
if (missingCounties.length > 0) {
  console.log('  ' + missingCounties.join(', '));
}
console.log();

// Verify known mappings
console.log('Verifying known County → Region mappings:');
let mappingErrors = 0;
Object.entries(KNOWN_MAPPINGS).forEach(([county, expectedRegion]) => {
  const actualRegions = countyRegionMap[county];
  if (!actualRegions) {
    console.log(`  [NOT IN DATA] ${county} — expected: ${expectedRegion}`);
  } else {
    const regions = [...actualRegions];
    const ok = regions.every(r => r === expectedRegion);
    if (ok) {
      console.log(`  ✓ ${county.padEnd(16)} → ${expectedRegion}`);
    } else {
      console.log(`  ✗ ${county.padEnd(16)} → expected "${expectedRegion}", found: ${regions.join(', ')}`);
      mappingErrors++;
    }
  }
});
console.log(mappingErrors === 0 ? '\n✓ All checked mappings are correct.\n' : `\n${mappingErrors} mapping error(s) found.\n`);

// Complete region→county listing
console.log('Complete Region → County mapping in data:');
Object.entries(regionCountyMap).sort(([a],[b]) => a.localeCompare(b)).forEach(([region, counties]) => {
  const sorted = [...counties].sort();
  console.log(`\n  ${region} (${sorted.length} counties):`);
  console.log(`    ${sorted.join(', ')}`);
});
console.log();

// ════════════════════════════════════════════════════════════════════════════
// CHECK 7 — "Unverified" Label Check
// ════════════════════════════════════════════════════════════════════════════
console.log('═'.repeat(70));
console.log('CHECK 7 — "UNVERIFIED" LABEL CHECK');
console.log('═'.repeat(70));

// Literal "Unverified" string anywhere in any field
const literalUnverified = [];
data.forEach((rec, idx) => {
  const hits = Object.entries(rec)
    .filter(([, v]) => typeof v === 'string' && v.includes('Unverified'))
    .map(([k]) => k);
  if (hits.length > 0) {
    literalUnverified.push({ idx, org: name(rec), fields: hits });
  }
});

if (literalUnverified.length === 0) {
  console.log('✓ No records contain the literal string "Unverified".\n');
} else {
  console.log(`Records containing literal "Unverified" — ${literalUnverified.length}:`);
  literalUnverified.forEach(({ idx, org, fields }) =>
    console.log(`  [${idx}] ${org} (in fields: ${fields.join(', ')})`));
  console.log();
}

// Count empty Contact_Name, Website, Source_URL (these render as "Unverified" in UI)
const emptyContactName = data.filter(r => isEmpty(r['Contact_Name']));
const emptyWebsite = data.filter(r => isEmpty(r['Website']));
const emptySourceURL = data.filter(r => isEmpty(r['Source_URL']));

console.log('Empty field counts (render as "Unverified" in UI):');
console.log(`  Contact_Name  : ${emptyContactName.length}`);
console.log(`  Website       : ${emptyWebsite.length}`);
console.log(`  Source_URL    : ${emptySourceURL.length}`);
console.log();

if (emptyContactName.length > 0) {
  console.log(`  Contact_Name blanks — ${emptyContactName.length} records (goal: ZERO):`);
  emptyContactName.forEach((rec, i) => {
    const idx = data.indexOf(rec);
    console.log(`    [${idx}] ${name(rec)}`);
  });
  console.log();
} else {
  console.log('  ✓ Contact_Name: ZERO blanks — goal met.\n');
}

if (emptyWebsite.length > 0) {
  console.log(`  Website blanks — ${emptyWebsite.length} records:`);
  emptyWebsite.forEach(rec => {
    const idx = data.indexOf(rec);
    console.log(`    [${idx}] ${name(rec)}`);
  });
  console.log();
}

if (emptySourceURL.length > 0) {
  console.log(`  Source_URL blanks — ${emptySourceURL.length} records:`);
  emptySourceURL.forEach(rec => {
    const idx = data.indexOf(rec);
    console.log(`    [${idx}] ${name(rec)}`);
  });
  console.log();
}

console.log('═'.repeat(70));
console.log('QC COMPLETE');
console.log('═'.repeat(70));
