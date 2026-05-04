#!/usr/bin/env node
// QC Check 12 — Naming Consistency
// Extracts FL_AG_CAMPAIGN_DATA from the HTML file and runs all checks

const fs = require('fs');
const path = require('path');

const htmlFile = path.join(__dirname, 'campaign_schedule_outreach.html');
const html = fs.readFileSync(htmlFile, 'utf8');

// Extract the JSON array assigned to window.FL_AG_CAMPAIGN_DATA
const match = html.match(/window\.FL_AG_CAMPAIGN_DATA\s*=\s*(\[[\s\S]*?\]);\s*(?:\/\/|<\/script>|\n\s*(?:let|var|const|window))/);
if (!match) {
  console.error('ERROR: Could not find window.FL_AG_CAMPAIGN_DATA in file.');
  process.exit(1);
}

let data;
try {
  data = JSON.parse(match[1]);
} catch (e) {
  console.error('ERROR: Failed to parse JSON:', e.message);
  process.exit(1);
}

console.log(`Loaded ${data.length} records.\n`);
console.log('='.repeat(72));

// ─── UTILITY ────────────────────────────────────────────────────────────────
function orgName(r) { return (r.Organization_or_Event_Name || '').trim(); }
function contact(r) { return (r.Contact_Name || '').trim(); }
function row(r) { return r.Row_Number || r.row_number || r.id || '?'; }

// ─── CHECK 1: REC — full "Republican Executive Committee" usage ──────────────
console.log('\n## CHECK 1 — Full "Republican Executive Committee" (should be "REC")\n');
const recFull = data.filter(r =>
  /republican executive committee/i.test(orgName(r))
);
if (recFull.length === 0) {
  console.log('  PASS — No records use the full name.');
} else {
  recFull.forEach(r => {
    console.log(`  ROW ${row(r)}: "${orgName(r)}"  |  Contact: "${contact(r)}"`);
  });
  console.log(`  TOTAL: ${recFull.length} record(s)`);
}

// ─── CHECK 2: Abbreviation inconsistencies ───────────────────────────────────
console.log('\n## CHECK 2 — Organization Name Abbreviation Inconsistencies\n');

// North Jax vs North Jacksonville
const northJax = data.filter(r => /north\s+jax\b/i.test(orgName(r)));
const northJacksonville = data.filter(r => /north\s+jacksonville\b/i.test(orgName(r)));
console.log(`  "North Jax" usage      : ${northJax.length} record(s)`);
northJax.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "North Jacksonville" usage: ${northJacksonville.length} record(s)`);
northJacksonville.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
if (northJax.length > 0 && northJacksonville.length > 0) {
  console.log('  INCONSISTENCY: Both forms in use.');
} else if (northJax.length === 0 && northJacksonville.length === 0) {
  console.log('  (No "North Jax/Jacksonville" orgs found.)');
} else {
  console.log('  OK — Only one form in use.');
}

// So. Florida / S. Florida / South Florida
console.log('');
const soFla  = data.filter(r => /\bso\.\s*florida\b/i.test(orgName(r)));
const sFla   = data.filter(r => /\bs\.\s*florida\b/i.test(orgName(r)));
const southFla = data.filter(r => /\bsouth\s+florida\b/i.test(orgName(r)));
console.log(`  "So. Florida" usage   : ${soFla.length} record(s)`);
soFla.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "S. Florida" usage    : ${sFla.length} record(s)`);
sFla.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "South Florida" usage : ${southFla.length} record(s)`);
southFla.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
const sfForms = [soFla.length > 0, sFla.length > 0, southFla.length > 0].filter(Boolean).length;
if (sfForms > 1) {
  console.log('  INCONSISTENCY: Multiple forms in use for South Florida.');
} else if (sfForms === 0) {
  console.log('  (No "South Florida" orgs found.)');
} else {
  console.log('  OK — Only one form in use.');
}

// Ft. vs Fort
console.log('');
const ftAbbr = data.filter(r => /\bft\.\s+\w/i.test(orgName(r)));
const fortFull = data.filter(r => /\bfort\s+\w/i.test(orgName(r)));
console.log(`  "Ft." abbreviation    : ${ftAbbr.length} record(s)`);
ftAbbr.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "Fort" full word      : ${fortFull.length} record(s)`);
fortFull.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
if (ftAbbr.length > 0 && fortFull.length > 0) {
  console.log('  INCONSISTENCY: Both "Ft." and "Fort" in use.');
} else if (ftAbbr.length === 0 && fortFull.length === 0) {
  console.log('  (No "Fort/Ft." orgs found.)');
} else {
  console.log('  OK — Only one form in use.');
}

// St. vs Saint
console.log('');
const stAbbr = data.filter(r => /\bst\.\s+\w/i.test(orgName(r)));
const saintFull = data.filter(r => /\bsaint\s+\w/i.test(orgName(r)));
console.log(`  "St." abbreviation    : ${stAbbr.length} record(s)`);
stAbbr.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "Saint" full word     : ${saintFull.length} record(s)`);
saintFull.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
if (stAbbr.length > 0 && saintFull.length > 0) {
  console.log('  INCONSISTENCY: Both "St." and "Saint" in use.');
} else if (stAbbr.length === 0 && saintFull.length === 0) {
  console.log('  (No "St./Saint" orgs found.)');
} else {
  console.log('  OK — Only one form in use.');
}

// Additional: "Co." vs "County"
console.log('');
const coAbbr = data.filter(r => /\bco\.\s+(?:REC|Farm|Republican|Cattlemen|Farm|Young)/i.test(orgName(r)));
// Broader check: orgs that have "Co." where context suggests County
const coAbbrBroad = data.filter(r => /\b\w+\s+Co\.\s+\w/i.test(orgName(r)));
const countyFull  = data.filter(r => /\bcounty\b/i.test(orgName(r)));
console.log(`  "Co." abbreviation (broad): ${coAbbrBroad.length} record(s)`);
coAbbrBroad.slice(0, 20).forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
if (coAbbrBroad.length > 20) console.log(`    ... and ${coAbbrBroad.length - 20} more`);
console.log(`  "County" full word    : ${countyFull.length} record(s) (showing first 5)`);
countyFull.slice(0, 5).forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));

// "Assoc." / "Assn." vs "Association"
console.log('');
const assocAbbr = data.filter(r => /\bassoc\.\b|\bassn\.\b/i.test(orgName(r)));
const assocFull = data.filter(r => /\bassociation\b/i.test(orgName(r)));
console.log(`  "Assoc./Assn." abbr   : ${assocAbbr.length} record(s)`);
assocAbbr.forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
console.log(`  "Association" full    : ${assocFull.length} record(s) (showing first 5)`);
assocFull.slice(0, 5).forEach(r => console.log(`    ROW ${row(r)}: "${orgName(r)}"`));
if (assocAbbr.length > 0 && assocFull.length > 0) {
  console.log('  INCONSISTENCY: Both "Assoc./Assn." and "Association" in use.');
}

// ─── CHECK 3: Venue names in Contact_Name ─────────────────────────────────────
console.log('\n## CHECK 3 — Venue Names in Contact_Name\n');
const venueWords = [
  'Center', 'Centre', 'Hall', 'Building', 'Room', 'Plaza', 'Arena',
  'Hotel', 'Restaurant', 'Club', 'Office', 'Library', 'Station',
  'Pavilion', 'Auditorium', 'Ballroom', 'Conference', 'Lodge',
  'Inn', 'Suites', 'Resort', 'Fairground', 'Barn', 'Ranch',
  'Farm', 'Market', 'Store', 'Grill', 'Café', 'Cafe', 'Diner',
  'Venue', 'Park', 'Field', 'Stadium', 'Complex', 'Campus',
  'Tower', 'Terrace', 'Manor', 'Estate', 'House'
];
const venueRegex = new RegExp('\\b(' + venueWords.join('|') + ')\\b', 'i');

const venueInContact = data.filter(r => {
  const c = contact(r);
  return c && venueRegex.test(c);
});

if (venueInContact.length === 0) {
  console.log('  PASS — No venue names detected in Contact_Name.');
} else {
  venueInContact.forEach(r => {
    console.log(`  ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
  });
  console.log(`  TOTAL: ${venueInContact.length} record(s)`);
}

// ─── CHECK 4: Farm Bureau — insurance agent contacts ────────────────────────
console.log('\n## CHECK 4 — Farm Bureau Insurance Agent Check\n');

const farmBureauRecords = data.filter(r =>
  /farm\s+bureau/i.test(orgName(r))
);
console.log(`  Total Farm Bureau records: ${farmBureauRecords.length}`);

// 4a: FB records where org also mentions Insurance/Financial
const fbInsurance = farmBureauRecords.filter(r =>
  /insurance|financial/i.test(orgName(r))
);
console.log(`  Farm Bureau + "Insurance/Financial" in org name: ${fbInsurance.length}`);
fbInsurance.forEach(r => {
  console.log(`    ROW ${row(r)}: Org="${orgName(r)}"  |  Contact="${contact(r)}"`);
});

// 4b: FB contact names containing "Agent" or "Insurance"
const fbAgentContact = farmBureauRecords.filter(r =>
  /agent|insurance/i.test(contact(r))
);
console.log(`  Farm Bureau contacts containing "Agent" or "Insurance": ${fbAgentContact.length}`);
fbAgentContact.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

// 4c: Same contact name appears in both FB records AND insurance orgs
const fbContacts = new Set(farmBureauRecords.map(r => contact(r).toLowerCase()).filter(Boolean));
const insuranceRecords = data.filter(r =>
  /insurance|financial\s+services/i.test(orgName(r)) &&
  !/farm\s+bureau/i.test(orgName(r))
);
const crossRef = insuranceRecords.filter(r =>
  fbContacts.has(contact(r).toLowerCase())
);
console.log(`  Cross-ref: Same contact in FB + non-FB insurance org: ${crossRef.length}`);
crossRef.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

if (fbInsurance.length === 0 && fbAgentContact.length === 0 && crossRef.length === 0) {
  console.log('  PASS — No insurance agent issues found in Farm Bureau records.');
}

// ─── CHECK 5: General Name Quality ──────────────────────────────────────────
console.log('\n## CHECK 5 — General Contact Name Quality\n');

// 5a: Single-word contact names
const singleWord = data.filter(r => {
  const c = contact(r);
  return c && /^\S+$/.test(c) && c.length > 1;
});
console.log(`  Single-word contact names: ${singleWord.length}`);
singleWord.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

// 5b: All-caps contact names
const allCaps = data.filter(r => {
  const c = contact(r);
  // Must be at least 2 chars, all letters uppercase, no lowercase letters
  return c && c.length > 1 && /[A-Z]/.test(c) && !/[a-z]/.test(c) && /[A-Z]{2,}/.test(c);
});
console.log(`\n  All-caps contact names: ${allCaps.length}`);
allCaps.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

// 5c: Contact names with numbers
const hasNumbers = data.filter(r => {
  const c = contact(r);
  return c && /\d/.test(c);
});
console.log(`\n  Contact names containing numbers: ${hasNumbers.length}`);
hasNumbers.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

// 5d: Extremely long contact names (>50 chars — likely a title or description)
const tooLong = data.filter(r => contact(r).length > 50);
console.log(`\n  Extremely long contact names (>50 chars): ${tooLong.length}`);
tooLong.forEach(r => {
  console.log(`    ROW ${row(r)}: Contact="${contact(r)}"  |  Org="${orgName(r)}"`);
});

// 5e: Empty / blank contact names
const empty = data.filter(r => !contact(r));
console.log(`\n  Empty/blank Contact_Name: ${empty.length}`);
if (empty.length <= 20) {
  empty.forEach(r => {
    console.log(`    ROW ${row(r)}: Org="${orgName(r)}"`);
  });
} else {
  empty.slice(0, 10).forEach(r => console.log(`    ROW ${row(r)}: Org="${orgName(r)}"`));
  console.log(`    ... and ${empty.length - 10} more`);
}

// ─── SUMMARY ────────────────────────────────────────────────────────────────
console.log('\n' + '='.repeat(72));
console.log('SUMMARY');
console.log('='.repeat(72));
console.log(`  CHECK 1 — REC full name usage         : ${recFull.length} issue(s)`);
const abbrevIssues = (
  (northJax.length > 0 && northJacksonville.length > 0 ? 1 : 0) +
  (sfForms > 1 ? 1 : 0) +
  (ftAbbr.length > 0 && fortFull.length > 0 ? 1 : 0) +
  (stAbbr.length > 0 && saintFull.length > 0 ? 1 : 0) +
  (assocAbbr.length > 0 && assocFull.length > 0 ? 1 : 0)
);
console.log(`  CHECK 2 — Abbreviation inconsistencies : ${abbrevIssues} category/ies with issues`);
console.log(`  CHECK 3 — Venue names in Contact_Name  : ${venueInContact.length} issue(s)`);
console.log(`  CHECK 4 — FB insurance agent contacts  : ${fbInsurance.length + fbAgentContact.length + crossRef.length} issue(s)`);
const nameQualityIssues = singleWord.length + allCaps.length + hasNumbers.length + tooLong.length;
console.log(`  CHECK 5 — Contact name quality         : ${nameQualityIssues} issue(s) (+ ${empty.length} empty)`);
console.log('='.repeat(72));
