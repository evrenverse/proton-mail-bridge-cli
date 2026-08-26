# Workflows

## Identify vendors from order mails (across all accounts)

```bash
pmb --json message search --text "order" --since 2026-01-01 --with-body
```

The agent extracts senders/vendors from the `from`/`body_text` fields.
Without `--account` → fan-out over all accounts.

## Sum up invoices sent to a client

```bash
pmb --json message search --folder Sent --to client@x.com --with-attachments
# → returns UIDs + attachment metadata (filename/size) directly in the result;
#   remember account/folder from the result — no separate `attachment list` needed
pmb --json --account work@example.com attachment download --uid 5,12,17 --all --dir ./invoices --folder Sent
```

The agent reads the PDFs and sums the amounts.

## Send mail (safely, with dry run)

```bash
# 1. Show the dry run
pmb --json compose send --to a@x.com --subject "Offer" --body "..." --dry-run
# 2. Get the user's confirmation
# 3. Actually send
pmb --json compose send --to a@x.com --subject "Offer" --body "..." --yes
```

Remember the `message_id` from the response for follow-up ops.

## Reply to a mail

```bash
# First get the UID from a search result
pmb --json message search --from supplier@company.com --subject "Order" --folder INBOX
# Then reply with account+folder+uid from the result
pmb --json --account me@proton.me compose reply --uid 42 --folder INBOX --body "Thanks, received." --dry-run
pmb --json --account me@proton.me compose reply --uid 42 --folder INBOX --body "Thanks, received." --yes
```

## Move mails into a folder

```bash
# UIDs from the search result: remember account and folder
# 1. Preview: which mails would actually be hit?
pmb --json --account me@proton.me message move --uid 10,11,12 --folder INBOX --to Archive --dry-run
# → count, risk, missing_uids, and sender/subject/date per message
# 2. Show the list to the user, then run it
pmb --json --account me@proton.me message move --uid 10,11,12 --folder INBOX --to Archive --yes
```

`missing_uids` is the usual sign of a wrong `--folder`: UIDs are unique per account+folder.

## Bulk cleanup (search → preview → delete)

```bash
pmb --json message search --from newsletter@example.com --folder INBOX --ids-only --limit 500
pmb --json --account me@proton.me message delete --uid <ids> --folder INBOX --dry-run
# → "permanent": false and "to": "<Trash>" means it is the reversible soft delete;
#   "risk": "critical" means the real run needs a human terminal (bulk ≥ 20)
```

Hand the dry run to the user and let them run the delete themselves when it is 🔴.

## Clean up a large mailbox (senders → criterion → folder-wise)

```bash
# 1. Who is responsible for the volume? Headers only, so it works on 30k messages.
pmb --json message senders --min-count 20
# → count, name, last_date, last_subject, list_unsubscribe per sender

# 2. Preview the selection across every folder -- one entry per folder.
pmb --json --account me@proton.me message bulk-delete --all-folders \
    --from newsletter@example.com --before 2026-01-01 --dry-run
# → total, folders[] with count/uids/messages, search.skipped_folders (All Mail, Trash)

# 3. The human runs it. Bulk >= 20 is 🔴 and needs a terminal.
pmb --json --account me@proton.me message bulk-delete --all-folders \
    --from newsletter@example.com --before 2026-01-01 --log ~/deleted.jsonl
```

Check `search.truncated` in every step: `true` means the selection is incomplete
(`reason: "limit"` → raise `--limit`, `0` = all; `"fetch_budget"` → raise `--max-fetch`).

`--list-unsubscribe` narrows to messages that offer an unsubscribe link — useful for finding
bulk senders, but it is **not** proof of advertising: project boards and portals set the header
on notifications that matter. Show the list, let the human decide.

## Get a login code out of a fresh mail

```bash
# Trigger the login FIRST, then read. The default window is 10 minutes, so a stale
# code from an earlier attempt cannot be picked up by mistake.
pmb --json message otp --from voelkner.de --since 10m
# → {"code": "867674", …, "ambiguous": false, "also_found": []}
#
# ambiguous: true means several messages in the window carried a candidate and the
# newest won. Check `also_found` (uid/from/date/shape, never the code) and re-run
# with a narrower --from before typing anything into a form.
#
# Exit 1 with "otp_not_found": nothing in the window -- widen --since, or the mail
# went to a folder other than INBOX/Spam (--folder).
# Exit 1 with "otp_ambiguous": the only candidates sat in a message that offers
# several, so none of them can be trusted. Read it yourself:
pmb --json message search --from voelkner.de --since 2026-08-26 --with-body --limit 1
```

## List unread mails across all accounts

```bash
pmb --json message list --unread --limit 50
```

Results are tagged by `account` — pass `--account` for follow-up ops.

## Download attachments (selectively)

```bash
pmb --json attachment list --uid 42 --folder INBOX
# → shows filename, index, size
pmb --json attachment download --uid 42 --index 0 --dir /tmp/downloads --folder INBOX --dry-run
# → target paths plus "overwrites": files that already exist and would be replaced
pmb --json attachment download --uid 42 --index 0 --dir /tmp/downloads --folder INBOX
```
