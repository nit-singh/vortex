# Cloudinary Upload Preset - Name vs ID

## Important: Use Preset NAME, Not UUID/PID

When configuring `NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET` in your `.env.local`, you should use the **preset name**, not the UUID/PID.

## How to Find Your Preset Name

### Step 1: Go to Upload Presets in Cloudinary

1. In Cloudinary Dashboard, click **Settings** (gear icon in bottom left)
2. Click **Upload** in the settings menu
3. Scroll down to **Upload presets** section

### Step 2: Find Your Preset

You'll see a list of presets. Each preset has:

- **Name**: The name you gave it (or auto-generated)
- **ID/PID**: A UUID like `13f4bc47-83e0-486f-8f7e-e9245126e457`

### Step 3: Use the Preset Name

**✅ CORRECT - Use the name:**

```env
NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET=my-video-preset
```

**❌ WRONG - Don't use the UUID:**

```env
NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET=13f4bc47-83e0-486f-8f7e-e9245126e457
```

## If Your Preset Doesn't Have a Name

If you see a preset with no name (just the UUID), you need to:

1. Click on the preset to edit it
2. Give it a name (e.g., `kyc-video-upload`)
3. Make sure it's set to **"Unsigned"** mode
4. Save the preset
5. Use that name in your `.env.local`

## Example .env.local

```env
NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME=dytdzrfwu
NEXT_PUBLIC_CLOUDINARY_UPLOAD_PRESET=kyc-video-upload
```

**Note**:

- No quotes needed
- No spaces
- Case-sensitive
- Use the name, not the UUID

## Quick Check

After updating `.env.local`:

1. Restart your dev server
2. Check console logs - you should see:
   ```
   📝 Upload Preset: kyc-video-upload
   ```
3. If you still see the UUID, the env variable isn't being read correctly
