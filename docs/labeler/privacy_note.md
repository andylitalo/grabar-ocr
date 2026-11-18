# Privacy note: Grabar OCR labeler

<!-- Draft v1, 2026-11-18, for the maintainer's review. Not legal advice. Shown at sign-up
     beside the contributor agreement (docs/labeler/contributor_agreement.md); it must stay
     true to how the labeler is built (docs/phase_12_hosted_labeler.md).
     {contact_email} is filled in by the labeler when it shows this page, from its deploy
     config (the LABELER_CONTACT_EMAIL environment variable), so the address isn't
     published in this public repo. -->

**Version 1 · 2026-11-18**

This note says what the labeler records about you, why, and who can see it. It's meant to
be clear rather than legalistic; ask if anything is unclear.

## What we record

- **Your account:** email address, first name, last name (if you gave one), whether you
  want to be credited by name, and which version of the contributor agreement you
  accepted, and when.
- **Your labeling activity:** every line you submit (the text as typed and as stored),
  when you submitted it and how long you spent on it, which buttons you used (for example
  Illegible or Can't Finish), and which pages you claimed and released.
- **Your accuracy results:** your practice-page results, whether you caught the planted
  errors, and whether your text matched the reference lines. We work out statistics from
  these, such as your catch rate and pages done.
- **Your status:** practice, trained or paused, and any alerts the maintainer received
  about your work.

## How we use it

- To run the labeler: your account, your claimed page, and resuming where you left off.
- To measure and publish the accuracy of the finished text.
- To give you feedback and your own statistics.
- To let the maintainer see when someone might want help, for example after repeated
  missed errors. Nothing happens automatically to your account; the maintainer gets in
  touch.
- To credit you, if you chose that.

We don't use third-party analytics or advertising, don't track you across other sites, and
never sell your information or share it beyond what this note describes. The labeler keeps
your sign-in token in your browser, along with any lines not yet saved, until the server
has them.

## Who sees what

| who | sees |
|---|---|
| you | your own activity and statistics |
| the maintainer | everything above, for every contributor |
| the public | the finished text; each line's submissions under an anonymous contributor number, including the text, when it was submitted and how long it took; the names of contributors who chose credit, in a list not linked to those numbers; overall accuracy figures |

Your email address, your statistics and your accuracy results are never published, and
your name is never committed to the public code repository.

## Where it's stored

- **Google Cloud** in the United States: the database, page images and app logs.
- **Firebase** (Google's sign-in service): your email and password. It also sends your
  invitation email. Your password is never visible to the project.
- **GitHub:** the public repository holds the finished text and the anonymous submissions;
  a private repository, readable only by the maintainer, holds the planted-error results,
  alert history and the list linking contributor numbers to names.
- **The maintainer's computer and email:** working copies while preparing releases, and
  alert emails about contributors' work.

## How long we keep it

- **Your account** is kept until you ask for it to be deleted.
- **Your submissions** are kept permanently, because the published text records where each
  line came from. If your account is deleted, they're attributed to an anonymous
  contributor.
- **Your accuracy results and alert history** are kept with the project's records. If your
  account is deleted, they're kept only under the anonymous number.
- **Backups** of the database are deleted after about a week, and **app logs** after about
  a month. Logs never contain your email or the text you typed.

## Your choices

- Change how you're credited at any time, in settings.
- Ask for a copy of what we hold about you, for a correction, or for your account to be
  deleted, by writing to the contact below.

## If you're in the EU or UK

Data protection law there (the GDPR and UK GDPR) gives you rights over your data. The
person responsible for it is Andy Ylitalo, at the contact below. We use your account and
activity to run the labeler you signed up for, and your accuracy results because the
project has a legitimate interest in measuring the text's accuracy; we publish your name
only because you asked us to. Your data is stored in the United States by Google and
GitHub, under their standard data-transfer terms. You can ask to see, correct, export or
delete your data, or object to how it's used, and you can complain to your local data
protection authority (in the UK, the ICO). One limit: the corrections you licensed can't be
removed from the published text, but after deletion they're no longer linked to you.

## Contact

Andy Ylitalo, {contact_email}.
