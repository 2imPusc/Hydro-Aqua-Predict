const serialNumber = "06M26042802";
const response = await fetch("https://thegreenlab.xyz/Devices/ByUser", {
  method: "GET",
  headers: {
    Authorization:
      "Basic " + btoa(`${process.env.TK_DHTB}:${process.env.MK_DHTB}`),
  },
});
const latestData = await response.json();
console.log(latestData);
