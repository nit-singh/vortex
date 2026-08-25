# Cloudinary Setup Guide

## Common Error: "Upload preset not found"

If you're getting this error, follow these steps:

### 1. Check Your Upload Preset in Cloudinary Dashboard

1. Go to [Cloudinary Dashboard](https://console.cloudinary.com)
2. Navigate to **Settings** → **Upload** (or go directly to Upload presets)
3. Find your upload preset or create a new one

### 2. Create/Configure Upload Preset

**To create a new upload preset:**

1. In Cloudinary Dashboard, go to **Settings** → **Upload**
2. Scroll down to **Upload presets** section
3. Click **Add upload preset**
4. Configure:
   - **Preset name**: Give it a name (e.g., `kyc-video-upload`)
   - **Signing mode**: Select **Unsigned** (required for client-side uploads)
   - **Folder**: Optional - set to `kyc-videos` if you want organized folders
   - **Resource type**: Select **Video**
   - **Allowed formats**: Leave default or specify `webm,mp4,mov`
   - **Max file size**: Set appropriate limit (e.g., 100MB)
5. Click **Save**

### 3. Get the Preset Name/ID

After creating the preset, you'll see it in the list. The preset can be identified by:

- **Preset name**: The name you gave it (e.g., `kyc-video-upload`)
- **Preset ID**: Sometimes shown as a UUID

**Important**: Use the **preset name** (not the UUID) in your `.env.local` file.

### 4. Update Your .env.local File

```env
NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME=your_cloud_name
NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET=kyc-video-upload
```

**Note**:

- Use the preset **name**, not the UUID
- Make sure there are no extra spaces or quotes
- The preset name is case-sensitive

### 5. Verify Your Configuration

Check your `.env.local` file:

```bash
# In your terminal
cat dashboard/.env.local
```

Make sure:

- ✅ Cloud name matches your Cloudinary dashboard
- ✅ Upload preset name matches exactly (case-sensitive)
- ✅ No quotes around the values
- ✅ No trailing spaces

### 6. Restart Your Development Server

After updating `.env.local`, restart your Next.js server:

```bash
# Stop the server (Ctrl+C)
# Then restart
npm run dev
```

### 7. Test the Upload

1. Open browser console (F12)
2. Complete the questionnaire and click "Finish"
3. Check the console logs for:
   - ✅ Cloud Name
   - ✅ Upload Preset
   - ✅ Upload response (should be 200 OK)

## Troubleshooting

### Error: "Upload preset not found"

- **Check**: Preset name in `.env.local` matches exactly (case-sensitive)
- **Check**: Preset is set to "Unsigned" mode
- **Check**: Preset exists in Cloudinary dashboard

### Error: "Invalid cloud name"

- **Check**: Cloud name in `.env.local` matches your Cloudinary dashboard
- **Check**: No typos in the cloud name

### Error: "CORS" or network errors

- **Check**: Upload preset is set to "Unsigned" mode
- **Check**: Browser console for CORS errors

### Video not appearing in Cloudinary

- **Check**: Media Library in Cloudinary dashboard
- **Check**: Look in the `kyc-videos/{userId}/` folder
- **Check**: Console logs for the `secure_url` - try opening it in a browser

## Quick Test

After setup, you can test by checking the console logs when uploading:

```
✅ Upload successful!
🔗 Video URL: https://res.cloudinary.com/...
🆔 Public ID: kyc-videos/user123/video-...
```

If you see these logs, the upload is working! 🎉
