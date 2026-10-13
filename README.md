# Photo Review

Finds duplicates and junk in your Apple Photos library so you can clean it up and free iCloud space.

Nothing is deleted until you've reviewed it and run `apply --yes`. macOS then asks you to confirm, and deleted photos stay in **Recently Deleted** for 30 days.

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
   cd /path/to/photo_review
   ```
   Use the folder where you cloned or downloaded this project. The first command you run installs everything automatically.
5. **Optional: add a Hugging Face token.** This is only to stop the "unauthenticated requests to the HF Hub" warning and get faster model downloads. Everything works without it.
   - Create a free **Read** token at https://huggingface.co/settings/tokens.
   - Copy the example settings file:
     ```sh
     cp .env.example .env
     ```
   - Open `.env`, remove the `#` and paste your token after `HF_TOKEN=`.
   - `.env` stays on your Mac and isn't committed to git.

---

## How to use it

Run these in order. Each step saves its results, so you can stop and come back later.

### Step 1: Prepare

```sh
uv run photo-review prepare
```

This does three things in one go, for every photo and video from the **last 12 months**:

1. **Scans** your library: Apple's quality scores, captions, labels, people and so on.
2. **Analyzes** each photo using a free AI model that runs entirely **on your Mac**. Nothing is uploaded. The first run downloads the model (about 600 MB). After that, only new photos are analyzed, so re-running it is quick.
3. **Finds duplicates and junk**: it groups similar shots, picks the best one in each group, and flags likely junk.

To choose different dates:
```sh
uv run photo-review prepare --from 2024-01-01 --to 2025-01-01
```

It's safe to re-run at any time. Your review decisions (step 2) are kept.

### Step 2: Review in your browser

```sh
uv run photo-review review
```

Your browser opens at **http://127.0.0.1:8765**. It only runs on your Mac.

- **Progress bar** at the top: how much you've reviewed and how many photos are marked for removal.
- **Tabs:** one per category, each with the number left to review. It shows ✓ when the category is finished.
- **Borders:**
  - **Dashed** border: a *suggestion*. Green means keep, red means remove.
  - **Solid** border: *your decision*.
- **Keep / Remove** buttons are on every photo. Click the same button again to clear it.
- **Finished items slide away**, so the next one is always at the top. Untick **Hide finished** to see them again.
- **Undo:** an **Undo** button appears after every action. You can also press **Z**.
- **Click a photo** to see it larger. Use the ← → arrow keys to flip through, and Keep / Remove work there too.
- **Duplicates tab:** each box is a group of similar shots. The ★ marks the suggested keeper, and the best score, sharpness and resolution in the group are in **bold**.
  - **Accept suggestion** keeps the ★ photo and removes the rest.
  - **Keep only this** keeps that photo and removes the rest. Use it when you prefer a different photo to the ★ one.
  - **Keep all** keeps every photo in the group.
- **Other tabs:**
  - Use the **Min confidence** slider to show only the most certain flags.
  - **Remove all** marks everything in the tab as remove. It asks you to confirm first.
- When a tab is finished, a **Next** button takes you to the next category with items left.
- **Marked for removal** tab (on the right): everything you've marked **Remove**, across all categories. This is exactly what `apply` will delete. Click **Keep instead** (or press **K**) to rescue a photo.

**Keyboard shortcuts** (press **?** in the page to see them):

| Where | Keys |
|---|---|
| Duplicates | **A** accept suggestion · **K** keep all · **1–9** keep only that photo · **↑ ↓** move between groups |
| Other tabs | **R** remove · **K** keep · arrow keys to move |
| Anywhere | **Space** enlarge · **Z** undo · **?** help |

Your decisions save automatically. Press **Ctrl+C** in the terminal to stop the review page.

> **Nothing happens in Photos yet.** Clicking Keep or Remove only saves your choice on your Mac (in `data/`). You can close the page and come back later, and your choices are still there. Photos is only touched when you run `apply --yes` in step 3.

### Step 3: Delete the removals

First do a **dry run** to see what would happen. Nothing changes in Photos.
```sh
uv run photo-review apply
```

When you're happy with it:
```sh
uv run photo-review apply --yes
```

> **Run this step from the Terminal app, not VS Code.** macOS needs permission for the app to access Photos, and VS Code's built-in terminal usually can't get it. Open **Terminal** and run:
> ```sh
> cd /path/to/photo_review && uv run photo-review apply --yes
> ```
> The first time, allow **Full Access** when macOS asks whether Terminal can access your photos.

- macOS shows a dialog asking you to confirm the deletion. Click **Delete** to go ahead, or cancel to leave everything as it is.
- Only photos you marked **Remove** are deleted. Photos marked **Keep**, or not decided yet, are left alone.
- Deleted items go to **Recently Deleted** in Photos for 30 days, so you can still recover them.
- The deletions sync to iCloud and free up space.

### Fallback: the Photo Review album

If the tool can't delete directly (for example, Photos access was denied), it puts the photos into a **Photo Review** album (under **My Albums**) instead. You can also ask for this on purpose with `apply --yes --album`. Then delete them yourself:

1. Open **Photos** and go to the **Photo Review** album.
2. Have a quick look through.
3. Select all (**⌘A**), then right-click and choose **Delete**.

The first time the album is used, macOS asks whether Terminal may control Photos. Click **OK**.

---

## Coming back later

| Situation | What to run |
|---|---|
| Carrying on with reviewing | `uv run photo-review review` |
| Used the album fallback but **haven't deleted yet** | `uv run photo-review review`. Your decisions are kept, and `apply --album` won't add the same photos twice. |
| **Deleted** photos yourself in Photos, or taken **new photos** since | `prepare`, then `review`. Deleted photos stop showing up, and only new photos are analyzed. Photos deleted by `apply --yes` are cleared automatically. |

If you're not sure, run `prepare` then `review`. It's always safe, and your decisions are kept.

---

## Doing older years

Repeat steps 1 to 3 with a different date range, for example:
```sh
uv run photo-review prepare --from 2024-01-01 --to 2025-01-01
uv run photo-review review
```

---

## Other commands

| Command | What it does |
|---|---|
| `uv run photo-review scan` / `analyze` / `classify` | Run the three parts of `prepare` one at a time. |
| `uv run photo-review inspect` | Summarizes what's been scanned: counts, Apple scores, labels and so on. |
| `uv run photo-review classify --min-confidence 0.7` | Re-flags and prints a summary with examples, showing only the more certain flags. |
| `uv run photo-review analyze --force` | Re-analyzes everything from scratch. |
| `uv run photo-review review --no-browser` | Starts the review page without opening a browser. |
| `uv run photo-review apply --yes --album` | Adds removals to the **Photo Review** album instead of deleting them. |
| `uv run photo-review apply --yes --album --reapply` | Re-adds items that were already added to the album. |
| `uv run photo-review --help` | Lists all commands. |

---

## Troubleshooting

- **"Could not get path to photo library database"** or **"Operation not permitted"**: Full Disk Access isn't on. See setup step 3, then quit and reopen the app.
- **Some photos are only in iCloud.** That's fine. The tool uses the preview images Photos keeps on your Mac.
- **`apply --yes` says "isn't letting this app access your Photos library"**:
  - Run it from the **Terminal** app instead of VS Code (see step 3).
  - If Terminal also fails, go to **System Settings → Privacy & Security → Photos** and set **Terminal** to **Full Access**.
- **The album fallback says "isn't letting this app control Photos"**, or the album doesn't appear: go to **System Settings → Privacy & Security → Automation** and switch on **Photos** under **Terminal**.
- **"address already in use" when starting `review`**: the review page is already running in another terminal. Use that one, or stop it with **Ctrl+C** first.
- **Start over completely:** delete the `data/` folder. This also deletes your review decisions. Then begin again at step 1 (`prepare`).

All data (scan results, analysis, decisions, thumbnails) is stored in `data/`, on your Mac only, and isn't committed to git.
