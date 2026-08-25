# Pathway Dashboard

A Next.js dashboard application for portfolio management with KYC and risk assessment features.

## Features

- **Authentication**: Login, registration, and password recovery
- **Consumer Dashboard**: Portfolio management, KYC submission, risk assessment
- **Company Dashboard**: Review KYC submissions, manage settings
- **Questionnaire**: 6-step onboarding process with document upload and video verification
- **Investment Risk Assessment**: Multi-question risk profiling

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Build for Production

```bash
npm run build
npm start
```

## Project Structure

```
dashboard/
├── app/
│   ├── (auth)/          # Authentication pages
│   ├── consumer/         # Consumer-facing pages
│   ├── company/          # Company-facing pages
│   └── layout.tsx        # Root layout
├── components/
│   ├── ui/               # Reusable UI components
│   └── layout/           # Layout components
├── lib/
│   ├── api.ts            # API client functions
│   └── utils.ts          # Utility functions
└── public/               # Static assets
```

## Environment Variables

Create a `.env.local` file:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME=your_cloud_name
NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET=your_upload_preset
```

### Cloudinary Setup (for video uploads)

1. Sign up for a free account at [Cloudinary](https://cloudinary.com)
2. Go to your Dashboard and copy your Cloud Name
3. Go to Settings > Upload and create an Upload Preset:
   - Set it to "Unsigned" for client-side uploads
   - Enable "Use filename" if you want custom naming
   - Set resource type to "Video"
4. Add these values to your `.env.local` file

## Key Pages

- `/login` - User login
- `/register` - User registration
- `/consumer/dashboard` - Consumer dashboard
- `/consumer/questionnaire` - 6-step onboarding questionnaire
- `/company/dashboard` - Company dashboard
- `/company/reviews` - KYC review management

## Technologies

- Next.js 14
- TypeScript
- Tailwind CSS
- Lucide React (icons)
- Axios (API calls)
