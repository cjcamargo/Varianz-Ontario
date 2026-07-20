type BrandLockupProps={variant?:"sidebar"|"hero";className?:string};

export function BrandMark({className=""}:{className?:string}){
  return <svg className={className} viewBox="0 0 48 48" role="img" aria-label="Varianz">
    <path className="brand-orbit warm" d="M8.2 14.1A19 19 0 0 1 34.9 7.8"/>
    <path className="brand-orbit warm" d="M7 18.2A19 19 0 0 0 19.1 41"/>
    <path className="brand-orbit green" d="M28.4 41A19 19 0 0 0 42 20"/>
    <path className="brand-track warm" d="M10.5 15.2 23.5 39.2"/>
    <path className="brand-track warm" d="M16.8 9.5 25.4 26.2"/>
    <path className="brand-track green" d="M25.4 26.2 39.2 9.2"/>
    <circle className="brand-node warm" cx="10.5" cy="15.2" r="2.8"/>
    <circle className="brand-node warm" cx="16.8" cy="9.5" r="2.8"/>
    <circle className="brand-node warm" cx="23.5" cy="39.2" r="2.8"/>
    <circle className="brand-node green" cx="25.4" cy="26.2" r="2.8"/>
    <circle className="brand-node green" cx="39.2" cy="9.2" r="2.8"/>
  </svg>;
}

export function BrandLockup({variant="sidebar",className=""}:BrandLockupProps){
  return <div className={`brand-lockup ${variant} ${className}`.trim()} aria-label="Varianz by Operion">
    <BrandMark className="brand-mark"/>
    <div className="brand-wordmark"><strong>VARIANZ</strong><span><i>by</i> OPERION</span></div>
  </div>;
}
