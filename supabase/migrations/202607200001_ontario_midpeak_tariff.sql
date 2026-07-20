alter table app.tariff_profile
  add column if not exists electricity_midpeak_per_kwh numeric
  check(electricity_midpeak_per_kwh >= 0);

comment on column app.tariff_profile.electricity_midpeak_per_kwh is
  'Versioned Ontario mid-peak electricity rate in profile currency per kWh.';
