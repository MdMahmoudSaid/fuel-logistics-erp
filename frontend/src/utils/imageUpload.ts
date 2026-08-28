export const IMAGE_UPLOAD_ACCEPT = '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp'

const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']

export function isAllowedImageFile(file: File) {
  const name = file.name.toLowerCase()
  return (
    ALLOWED_IMAGE_TYPES.has(file.type) &&
    ALLOWED_IMAGE_EXTENSIONS.some((extension) => name.endsWith(extension))
  )
}
