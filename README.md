# Tesla Order Status Dashboard

Track every step of your Tesla order with a dashboard that highlights VIN information, delivery blockers, and historical snapshots. The easiest way to use it is the hosted site at **[tesla-tracker.rivsoft.org](https://tesla-tracker.rivsoft.org/)**—no installs or servers required.

> **Important:** This community project is not affiliated with Tesla. You authenticate with your own Tesla account, and the data used to render the dashboard never leaves your browser.

---

## Try It Now
1. Visit [tesla-tracker.rivsoft.org](https://tesla-tracker.rivsoft.org/).
2. Click **Log In** to open Tesla's official sign-in page in a new tab.
3. After signing in, copy the full callback URL Tesla displays and paste it back into the dashboard form.
4. The page refreshes with your order timeline, VIN insights, delivery blockers, and task list.
5. Use **Refresh Orders** anytime you want the latest data, and open **History** to compare with older snapshots that stay in your browser.

Need to reset everything? Use **Logout** or clear the site data in your browser—no data is kept on the server.

---

## Highlights
- **Live order view**: Keep tabs on VIN assignment, delivery tasks, financing, registration, and raw payload details.
- **Snapshot history**: Capture browser-only versions of each update and see what changed at a glance.
- **On-demand refresh**: Pull new data from Tesla's Owner API whenever you like.
- **Dark-mode friendly**: Carefully tuned colors for quick scanning day or night.

---

## Privacy & Safety
- OAuth tokens are stored in your browser (IndexedDB) and are only sent to the server for the single request you initiate.
- Snapshot history and diffing live entirely in your browser (localStorage); nothing is uploaded.
- Lightweight visit metrics stay anonymized and exist solely to help the maintainer understand aggregate usage of the hosted site.
- Handle any downloaded data the same way you would treat information inside the Tesla app.

---

## Questions or Issues?
The best place to report bugs, ask for help, or request features is the [GitHub Issues page](https://github.com/Rivsoft/tesla-order-status/issues).

When opening an issue, please share:
- A brief description of the problem or idea.
- Steps to reproduce it (if applicable).
- Screenshots or logs that illustrate the issue (scrub personal info first).

Check existing issues before filing a new one—your question might already be answered.

---

## Want to Self-Host?
Self-hosting is totally optional. If you prefer to run your own instance, clone this repository and read `docs/TECHNICAL_GUIDE.md` for detailed setup steps, architecture notes, and troubleshooting tips. Keep your Tesla credentials secure and avoid exposing the app to the public internet without proper safeguards.

---

## Contributing
Pull requests are welcome! Focus on user experience, privacy, and accessibility, and update the README whenever you add a behavior end users should know about. Please do not include personal Tesla data in commits or screenshots.

---

## Credits & Disclaimer
Built by Tesla owners for fellow owners. This project is provided "as is" with no warranty. Use at your own risk, and always protect your Tesla account details.

