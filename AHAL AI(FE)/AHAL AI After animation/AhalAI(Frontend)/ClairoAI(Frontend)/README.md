# Clairo AI Frontend

Production frontend for Clairo AI — an AI-powered code intelligence tool.

## Tech Stack

- **Next.js 14** (App Router)
- **TypeScript**
- **Tailwind CSS**
- **Framer Motion** (animations)
- **Lucide Icons**
- **Sonner** (toasts)

## Getting Started

```bash
# Install dependencies
npm install

# Run the dev server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Backend

The frontend connects to the FastAPI backend at `http://127.0.0.1:8000/api/v1`.

To override the API URL, set the `NEXT_PUBLIC_API_URL` environment variable.

## Project Structure

```
app/
  layout.tsx          # Root layout
  page.tsx            # Landing page
  (dashboard)/
    layout.tsx        # Dashboard shell (sidebar + topbar)
    page.tsx          # Dashboard home
    code/page.tsx     # Code analysis
    folder/page.tsx   # Folder upload
    history/page.tsx  # Session history
components/
  animations/         # Framer Motion components
  cards/              # Result card + panel
  layout/             # Sidebar + TopBar
  ui/                 # Skeleton, Toaster
hooks/                # useAnalyze, useUpload
lib/                  # API client, utilities
types/                # TypeScript interfaces
styles/               # Global CSS
```
