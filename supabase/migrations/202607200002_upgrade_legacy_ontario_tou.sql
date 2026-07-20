update app.tariff_profile
set preset = 'Ontario regulated TOU · seasonal',
    tou_windows = '[
      {"label":"midpeak","days":"mon-fri","season":"summer","start":"07:00","end":"11:00"},
      {"label":"peak","days":"mon-fri","season":"summer","start":"11:00","end":"17:00"},
      {"label":"midpeak","days":"mon-fri","season":"summer","start":"17:00","end":"19:00"},
      {"label":"peak","days":"mon-fri","season":"winter","start":"07:00","end":"11:00"},
      {"label":"midpeak","days":"mon-fri","season":"winter","start":"11:00","end":"17:00"},
      {"label":"peak","days":"mon-fri","season":"winter","start":"17:00","end":"19:00"}
    ]'::jsonb
where preset in ('Ontario winter · schedule only', 'Ontario summer · schedule only');
