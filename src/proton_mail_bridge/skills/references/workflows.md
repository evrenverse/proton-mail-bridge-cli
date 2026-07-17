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
pmb --json --account me@proton.me message move --uid 10,11,12 --folder INBOX --to Archive --yes
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
pmb --json attachment download --uid 42 --index 0 --dir /tmp/downloads --folder INBOX
```
