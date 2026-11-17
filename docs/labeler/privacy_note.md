# Privacy note: Grabar OCR labeler

<!-- Draft v1, 2026-11-17, for the maintainer's review. Not legal advice. Shown at sign-up
     beside the contributor agreement (docs/labeler/contributor_agreement.md); it must stay
     true to how the labeler is built (docs/phase_12_hosted_labeler.md).
     {contact_email} is filled in by the labeler when it shows this page, from its deploy
     config (the LABELER_CONTACT_EMAIL environment variable), so the address isn't
     published in this public repo. -->

**Version 1 · 2026-11-17**

This note says what the labeler records about you, why, and who can see it.

## What we record

- **Your account:** email address, first name, last name (if you gave one), whether you
  want to be credited by name, and which version of the contributor agreement you
  accepted, and when.
- **Your labeling activity:** every line you submit (the text as typed and as stored),
  when you submitted it and how long you spent on it, which buttons you used (for example
  Illegible or Can't Finish), and which pages you claimed and released.
- **Your accuracy results:** whether you caught the planted errors, and whether your text
  matched the reference lines. We work out statistics from these, such as your catch rate
  and pages done.

## How we use it

- To run the labeler: your account, your claimed page, and resuming where you left off.
- To measure and publish the accuracy of the finished text.
- To give you feedback and your own statistics.
- To let the maintainer see when someone might want help, for example after repeated
  missed errors. Nothing happens automatically to your account; the maintainer gets in
  touch.
- To credit you, if you chose that.

We do analyze your labeling activity, as described here. We don't use third-party
analytics or advertising, don't track you across other sites, and never sell or share your
information. The labeler keeps your sign-in token in your browser, along with any lines not
yet saved, until the server has them.

## Who sees what

| who | sees |
|---|---|
| you | your own activity and statistics |
| the maintainer | everything above, for every contributor |
| trusted labelers who settle disagreements | the competing texts of a line, not who typed them |
| the public | the finished text, with each submission under an anonymous contributor number; the names of contributors who chose credit; overall accuracy figures |

Your email address, your statistics and your accuracy results are never published.

## Where it's stored

On Google Cloud in the United States, and in Google's Firebase sign-in service, which
holds your email and password. Your password is never visible to the project.

## How long we keep it

- **Your account** is kept until you delete it.
- **Your submissions** are kept permanently, because the published text records where each
  line came from. If you delete your account, they're attributed to an anonymous
  contributor.
- **Backups** of the database are deleted after about a week.

## Your choices

- Change how you're credited at any time, in settings.
- Ask for a copy of what we hold about you, or ask us to delete your account, by writing to
  the contact below.

## Contact

Andy Ylitalo, {contact_email}.
