export function hasActivePremium(user) {
  if (!user?.is_premium) {
    return false;
  }

  if (!user?.premium_expires_at) {
    return false;
  }

  const expiresAt = new Date(user.premium_expires_at);
  if (Number.isNaN(expiresAt.getTime())) {
    return false;
  }

  return expiresAt.getTime() > Date.now();
}
