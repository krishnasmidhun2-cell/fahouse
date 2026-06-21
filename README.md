# Meter Cost Analyzer

This repository contains **Meter Cost Analyzer**, a mobile‑friendly web application built with [Next.js](https://nextjs.org/). It helps you track your bi‑monthly electricity meter readings, understand how your usage patterns affect your bill, and simulate potential savings by reducing consumption in different load categories.

## Features

- **Add Billing Cycles** – Enter start and end dates, units consumed during Normal, Peak and Off‑Peak periods, the total bill amount, and optional notes. Data is stored in your browser’s local storage.
- **Dashboard** – View the latest bill amount, total units used, the highest usage category, and see changes compared to the previous cycle.
- **Charts & Analysis** – Visualize your bill trend, usage trend, load shares, comparison between current and previous cycles, and changes in usage categories. A reduction simulator helps you estimate savings by reducing consumption percentages.
- **Local‑only Storage** – All data is kept in local storage; no backend is required. You can clear your browser data to reset.

## Getting Started

To run the app locally, you need [Node.js](https://nodejs.org/) installed.

1. **Clone the repository**

   ```bash
   git clone https://github.com/krishnasmidhun2-cell/fahouse.git
   cd fahouse
   ```

2. **Install dependencies**

   Use npm or yarn to install the package dependencies listed in `package.json`.

   ```bash
   npm install
   # or
   yarn install
   ```

3. **Run the development server**

   ```bash
   npm run dev
   # or
   yarn dev
   ```

   Then open [http://localhost:3000](http://localhost:3000) in your browser. You should see the dashboard page.

4. **Build for production**

   To build the optimized production bundle and start a server:

   ```bash
   npm run build
   npm start
   ```

## How to Use the App

1. **Add your first cycle** – Navigate to the **Add Cycle** page using the top navigation. Fill in the start and end dates (covering exactly two months), enter the units consumed during each load period, the total amount billed, and any notes. Click **Save Cycle**. You will be redirected to the dashboard.

2. **View your dashboard** – On the dashboard, you’ll see cards displaying the latest bill amount, total units consumed, the category with the highest usage, and changes compared to the previous cycle if available. A “Main Reason” card highlights which load category increased the most.

3. **Explore graphs** – Open the **Graphs** page to switch between various charts:

   - **Bill Trend** – A line chart showing how your total bill changes over time.
   - **Usage Trend** – A multi‑line chart depicting Normal, Peak, and Off‑Peak unit trends.
   - **Load Share** – A stacked bar chart showing how each category contributes to total consumption in each cycle.
   - **Latest Share** – A pie (doughnut) chart of the most recent cycle’s usage shares.
   - **Current vs Previous** – A bar chart comparing units for the latest cycle with the previous one.
   - **Change Impact** – A bar chart showing the increase or decrease in usage per category between the latest and previous cycles.
   - **Reduction Simulator** – Adjust the percentage reduction for Normal, Peak and Off‑Peak loads to see an estimated new bill based on the average rate of the latest cycle. This estimate doesn’t account for fixed charges or slab pricing but helps illustrate potential savings.

4. **Manage cycles** – All cycles are stored in your browser. Currently there is no edit or delete feature; if you need to reset, clear your browser’s local storage for the site.

## Notes

- The app does not require a backend server. All data is saved in local storage. Make sure not to clear your browser storage if you wish to preserve your history.
- For a more accurate estimation of savings, tariff rates per load type could be added to the app in the future. Currently the reduction simulator uses the latest cycle’s average per‑unit cost.
- Feel free to fork and enhance this project. Pull requests are welcome!
