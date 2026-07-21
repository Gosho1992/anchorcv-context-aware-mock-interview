alter table public.anchor_users
add column if not exists is_premium boolean not null default false;

alter table public.anchor_users
add column if not exists premium_expires_at timestamptz null;

update public.anchor_users
set
  is_premium = coalesce(is_paid, false),
  premium_expires_at = case
    when coalesce(is_paid, false) and premium_expires_at is null then now() + interval '90 days'
    else premium_expires_at
  end
where coalesce(is_paid, false) = true;
