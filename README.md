# School Menu Feed

Daily breakfast + lunch menu for Three Creeks K-8 (Jeffco) pulled from SchoolCafé and published as an ICS feed.

- Feed: `webcal://boda1985.github.io/school-menu-feed/menu.ics`
- Runs daily via GitHub Actions (`.github/workflows/update-menu.yml`); use "Run workflow" to refresh manually.
- Change grade: edit `Grade=` in both URLs in `MENUS` in `schoolcafe_to_ics.py`.
