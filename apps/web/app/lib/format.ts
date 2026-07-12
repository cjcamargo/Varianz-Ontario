export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export function fmt(value:number|null|undefined, digits=1){
  return value==null?"—":value.toLocaleString(undefined,{maximumFractionDigits:digits,minimumFractionDigits:digits});
}

export function date(value:string){
  return new Date(value).toLocaleString("en-CA",{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
}
