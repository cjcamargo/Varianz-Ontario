alter table app.tariff_profile
  add column if not exists tou_windows jsonb not null default '[]'::jsonb,
  add column if not exists preset text;

comment on column app.tariff_profile.tou_windows is
  'Reviewed site-local time-of-use windows used for interval classification.';

comment on column app.tariff_profile.preset is
  'Optional named schedule preset; rates remain user-supplied and sourced.';
