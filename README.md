# Photo Review

Finds duplicates and junk in your Apple Photos library so you can clean it up and free iCloud space.

It **never deletes anything**. It puts photos you choose into review albums in Photos, and you delete them yourself.

What it looks for:

- **Duplicates**: groups of similar shots. It suggests the best one to keep.
- **Screenshots** and screen recordings.
- **Documents and receipts**: receipts, documents, QR codes and signs.
- **Forwarded and web images**: memes, and images saved from Reddit, Safari, ChatGPT, WhatsApp and similar apps.
- **Blurry, dark and accidental shots.**
- **Low-resolution images.**
- **Short videos** (under 3 seconds).

These photos are never flagged as junk:

- Favorites (♥).
- Photos you edited yourself. Camera effects like Portrait mode don't count as edits.
- Photos of people you've named in Photos. These can still be flagged as duplicates.

---

## One-time setup

You only need to do this once.

1. **Install Homebrew** if you don't have it. See https://brew.sh.
2. **Install uv**, the Python tool this project uses:
   ```sh
   brew install uv
   ```
3. **Give VS Code (or Terminal) Full Disk Access.** Without this it can't read your Photos library.
   - Open **System Settings → Privacy & Security → Full Disk Access**.
   - Turn on **Visual Studio Code**, or **Terminal** if you run commands from Terminal.
   - **Quit and reopen** that app.
4. **Open a terminal in this folder:**
   ```sh
   cd ~/Documents/Development/photo_review
   ```
   The first command you run installs everything automatically.

---

## How to use it

Run these in order. Each step saves its results, so you can stop and come back later.

### Step 1: Scan your library

```sh
uv run photo-review scan
```

This reads details for every photo and video from the **last 12 months**: Apple's quality scores, captions, labels, people and so on.

To choose different dates:
```sh
uv run photo-review scan --from 2024-01-01 --to 2025-01-01
```

### Step 2: Analyze the images

```sh
uv run photo-review analyze
```

This looks at each photo using a free AI model that runs entirely **on your Mac**. Nothing is uploaded.

- The first run downloads the model (about 600 MB).
- It only processes photos it hasn't seen before, so re-running it is quick.

### Step 3: Find duplicates and junk

```sh
uv run photo-review classify
```

This groups similar shots, picks the best one in each group, and flags likely junk. It prints a summary with examples.

It's safe to re-run at any time. Your review decisions (step 4) are kept.

### Step 4: Review in your browser

```sh
uv run photo-review review
```

Your browser opens at **http://127.0.0.1:8765**. It only runs on your Mac.

- **Tabs** at the top: one per category, each showing how many items are left to review.
- **Borders:**
  - **Dashed** border: a *suggestion*. Green means keep, red means remove.
  - **Solid** border: *your decision*.
- **Keep / Remove** buttons are on every photo. Click the same button again to undo.
- **Click a photo** to see it larger, with Apple's description. Press Esc or click to close.
- **Duplicates tab:** each row is a group of similar shots. The ★ marks the suggested keeper.
  - **Accept suggestion** keeps the ★ photo and removes the rest.
  - **Keep all** keeps every photo in the group.
- **Other tabs:**
  - Use the **Min confidence** slider to show only the most certain flags.
  - **Remove all shown** marks everything on screen as remove.
- **Pending only** hides items you've already decided on.

Your decisions save automatically. Press **Ctrl+C** in the terminal to stop the review page.

> **Nothing happens in Photos yet.** Clicking Keep or Remove only saves your choice on your Mac (in `data/`). You can close the page and come back later, and your choices are still there. Photos is only touched when you run `apply --yes` in step 5.

### Step 5: Put the removals into albums

First do a **dry run** to see what would happen. Nothing changes in Photos.
```sh
uv run photo-review apply
```

When you're happy with it:
```sh
uv run photo-review apply --yes
```

- This creates a **Photo Review** folder in Photos, with one album per category plus an **All** album.
- Only photos you marked **Remove** are added. Photos marked **Keep**, or not decided yet, are left alone.
- The first time, macOS asks whether VS Code (or Terminal) may control Photos. Click **OK**.
- Running it again only adds new decisions.

### Step 6: Delete in Photos (you do this)

1. Open **Photos** and go to **Photo Review → All**.
2. Have a quick look through.
3. Select all (**⌘A**), then right-click and choose **Delete**.
4. Deleted items go to **Recently Deleted** for 30 days, so you can still recover them.
5. The deletions sync to iCloud and free up space.

---

## Coming back later

| Situation | What to run |
|---|---|
| Carrying on with reviewing | `uv run photo-review review` |
| Added to albums but **haven't deleted yet** | `uv run photo-review review`. Your decisions are kept, and `apply` won't add the same photos twice. |
| **Deleted** photos in Photos | `scan`, then `classify`, then `review`. The scan clears out deleted photos so they stop showing up. |
| Taken **new photos** since | `scan`, `analyze`, `classify`, then `review`. Only new photos are processed. |

If you're not sure, run all four in order. It's always safe, and your decisions are kept.

---

## Doing older years

Repeat steps 1 to 6 with a different date range, for example:
```sh
uv run photo-review scan --from 2024-01-01 --to 2025-01-01
uv run photo-review analyze
uv run photo-review classify
uv run photo-review review
```

---

## Other commands

| Command | What it does |
|---|---|
| `uv run photo-review inspect` | Summarizes what's been scanned: counts, Apple scores, labels and so on. |
| `uv run photo-review classify --min-confidence 0.7` | Shows only the more certain flags in the summary. |
| `uv run photo-review analyze --force` | Re-analyzes everything from scratch. |
| `uv run photo-review review --no-browser` | Starts the review page without opening a browser. |
| `uv run photo-review apply --reapply` | Re-adds items that were already added to albums. |
| `uv run photo-review --help` | Lists all commands. |

---

## Troubleshooting

- **"Could not get path to photo library database"** or **"Operation not permitted"**: Full Disk Access isn't on. See setup step 3, then quit and reopen the app.
- **Some photos are only in iCloud.** That's fine. The tool uses the preview images Photos keeps on your Mac.
- **`apply --yes` does nothing or fails.** Go to **System Settings → Privacy & Security → Automation** and allow VS Code (or Terminal) to control **Photos**.
- **Start over completely:** delete the `data/` folder. This also deletes your review decisions. Then begin again at step 1.

All data (scan results, analysis, decisions, thumbnails) is stored in `data/`, on your Mac only, and isn't committed to git.
