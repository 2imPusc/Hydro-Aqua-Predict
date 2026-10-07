require("dotenv").config({ quiet: true, path: require("path").join(__dirname, "..", ".env") });
const { Command } = require("commander");
const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");

const program = new Command();

const BASE_URL = "https://thegreenlab.xyz";
const TK = process.env.TK_DHTB;
const MK = process.env.MK_DHTB;

if (!TK || !MK) {
  console.error("Missing TK_DHTB or MK_DHTB in .env file.");
  process.exit(1);
}

// ---------------------------------------------------------
// File & Directory Management (The Data Architecture)
// ---------------------------------------------------------
const EXPORT_DIR = path.join(__dirname, "..", "data", "greenlab", "exports");
const DIRS = {
  all_data: path.join(EXPORT_DIR, "all_data"),
  intervals: path.join(EXPORT_DIR, "intervals"),
  snapshots: path.join(EXPORT_DIR, "snapshots"),
};

// Ensure directories exist
Object.values(DIRS).forEach((dir) => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
});

// Load stations to get region
let stationsRegistry = [];
try {
  const yamlContent = fs.readFileSync(path.join(__dirname, "stations.yaml"), "utf8");
  const parsed = yaml.load(yamlContent);
  if (parsed && parsed.stations) {
    stationsRegistry = parsed.stations;
  }
} catch (err) {
  console.warn("Warning: Could not load stations.yaml for region mapping.");
}

function getRegion(serial) {
  const st = stationsRegistry.find(s => s.serial === serial);
  return (st && st.region) ? st.region.toUpperCase() : "UNKNOWN";
}

function getAutoFilePath(type, serial, options) {
  const region = getRegion(serial);
  const ext = options.csv ? "csv" : "json";
  
  if (type === "all") {
    // 06M26042804_HAIPHONG_All.csv
    return path.join(DIRS.all_data, `${serial}_${region}_All.${ext}`);
  } else if (type === "snapshot") {
    // 06M26042804_HAIPHONG_Latest.json
    return path.join(DIRS.snapshots, `${serial}_${region}_Latest.${ext}`);
  } else if (type === "interval") {
    // 06M26042804_HAIPHONG_20260701_to_20260704.csv
    const sDate = options.start ? options.start.replace(/-/g, "") : "Start";
    const eDate = options.end ? options.end.replace(/-/g, "") : "End";
    return path.join(DIRS.intervals, `${serial}_${region}_${sDate}_to_${eDate}.${ext}`);
  } else if (type === "history") {
    return path.join(DIRS.intervals, `${serial}_${region}_${options.period}.${ext}`);
  }
  return path.join(EXPORT_DIR, `output.${ext}`);
}

// ---------------------------------------------------------
// API Helper
// ---------------------------------------------------------
async function apiFetch(endpoint, throwError = false, expectCsv = false) {
  const authHeader = "Basic " + Buffer.from(`${TK}:${MK}`).toString("base64");
  const url = `${BASE_URL}${endpoint}`;

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { Authorization: authHeader },
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText} - ${await response.text()}`);
    }

    const contentType = response.headers.get("content-type");
    // GreenLab's DataByDate endpoint can return CSV without a CSV content
    // type. The caller knows when --csv was requested, so do not attempt JSON.
    if (expectCsv || (contentType && contentType.includes("csv"))) {
      return await response.text();
    }
    return await response.json();
  } catch (err) {
    if (throwError) throw err;
    console.error(`Request failed for ${url}`);
    console.error(err.message);
    process.exit(1);
  }
}

function pivotToCsv(data) {
  // Extract readings if it's a Snapshot format
  let arr = data;
  if (!Array.isArray(arr) && arr && arr.devices && arr.devices.length > 0) {
      arr = arr.devices[0].readings;
      if (arr) {
          arr.forEach(r => {
             r.DeviceSerialNumber = arr.devices?.[0]?.DeviceSerialNumber || "Unknown";
             r.Date = arr.devices?.[0]?.latestReceivedDate || "";
          });
      }
  }
  
  if (!Array.isArray(arr) || arr.length === 0) return null;
  
  const map = new Map();
  const sensors = new Set();
  
  for (const row of arr) {
     if (!row || typeof row !== 'object') continue;
     const date = row.Date || row.ReceivedDate || row.latestReceivedDate || row.FetchedAt || "";
     const device = row.DeviceSerialNumber || "Unknown";
     
     // Skip rows that don't have a sensor value
     if (row.SensorType === undefined || row.Value === undefined) continue;
     
     const key = `${date}|${device}`;
     if (!map.has(key)) map.set(key, { fetchedAt: date, device: device });
     map.get(key)[row.SensorType] = row.Value;
     sensors.add(row.SensorType);
  }
  
  if (sensors.size === 0) return null;
  
  const sensorArray = Array.from(sensors).sort();
  let csv = `device,fetchedAt,${sensorArray.join(",")}\n`;
  
  // Sort chronologically
  const sortedRows = Array.from(map.values()).sort((a, b) => a.fetchedAt.localeCompare(b.fetchedAt));
  
  for (const row of sortedRows) {
     const vals = sensorArray.map(s => row[s] !== undefined ? row[s] : "");
     csv += `${row.device},${row.fetchedAt},${vals.join(",")}\n`;
  }
  return csv;
}

function outputData(data, outFile) {
  const isString = typeof data === "string";
  const content = isString ? data : JSON.stringify(data, null, 2);
  fs.writeFileSync(outFile, content, "utf8");
  console.log(`✅ Data saved successfully to: ${outFile}`);
  
  // Auto Pivot to CSV if it was saved as JSON
  if (!isString && outFile.endsWith(".json")) {
      const csvStr = pivotToCsv(data);
      if (csvStr) {
          const csvFile = outFile.replace(".json", ".csv");
          fs.writeFileSync(csvFile, csvStr, "utf8");
          console.log(`✅ Pivoted CSV saved successfully to: ${csvFile}`);
      }
  }
}

// ---------------------------------------------------------
// CLI Commands
// ---------------------------------------------------------
program
  .name("fetch_api")
  .description("CLI to fetch data from GreenLab REST APIs with Automated Data Architecture")
  .version("1.1.0");

program
  .command("devices")
  .description("Xem thiết bị được cấp quyền")
  .option("-o, --out <file>", "Lưu kết quả ra file cụ thể (tùy chọn)")
  .action(async (options) => {
    const data = await apiFetch("/Devices/ByUser");
    const outFile = options.out || path.join(EXPORT_DIR, "devices.json");
    outputData(data, outFile);
  });

program
  .command("latest")
  .description("Dữ liệu mới nhất (tất cả hoặc 1 thiết bị)")
  .option("-s, --serial <serialNumber>", "SerialNumber của 1 thiết bị")
  .option("-o, --out <file>", "Ghi đè file đầu ra (tùy chọn)")
  .action(async (options) => {
    let endpoint = "/Datums/LastestDataByAllDevices";
    let outFile = options.out;
    
    if (options.serial) {
      endpoint = `/Datums/LastestDataByDevice?DeviceSerialNumber=${options.serial}`;
      if (!outFile) outFile = getAutoFilePath("snapshot", options.serial, { csv: false });
    } else {
      if (!outFile) outFile = path.join(DIRS.snapshots, "AllDevices_Latest.json");
    }
    
    const data = await apiFetch(endpoint);
    outputData(data, outFile);
  });

program
  .command("history")
  .description("Dữ liệu lịch sử gần đây của 1 sensor")
  .requiredOption("-s, --serial <serialNumber>", "SerialNumber của thiết bị")
  .requiredOption("-t, --sensor <sensorType>", "Sensor Type (VD: COD, NH4, pH, Temp, TSS)")
  .requiredOption("-p, --period <period>", "Khoảng thời gian: 1h, 24h, 7d, 30d")
  .option("-o, --out <file>", "Ghi đè file đầu ra (tùy chọn)")
  .action(async (options) => {
    let endpoint = "";
    const baseParams = `?DeviceSerialNumber=${options.serial}&SensorType=${options.sensor}`;

    switch (options.period) {
      case "1h": endpoint = `/Datums/LastHour${baseParams}`; break;
      case "24h": endpoint = `/Datums/Last24Hours${baseParams}`; break;
      case "7d": endpoint = `/Datums/Last7Days${baseParams}`; break;
      case "30d": endpoint = `/Datums/Last30Days${baseParams}`; break;
      default:
        console.error("Period không hợp lệ. Hãy dùng 1h, 24h, 7d, 30d");
        process.exit(1);
    }
    const data = await apiFetch(endpoint);
    const outFile = options.out || getAutoFilePath("history", options.serial, { period: `${options.sensor}_${options.period}`, csv: false });
    outputData(data, outFile);
  });

program
  .command("by-date")
  .description("Dữ liệu theo khoảng ngày")
  .requiredOption("-s, --serial <serialNumber>", "SerialNumber của thiết bị")
  .requiredOption("--start <date>", "Ngày bắt đầu (VD: 2026-07-01)")
  .requiredOption("--end <date>", "Ngày kết thúc (VD: 2026-07-04)")
  .option("--csv", "Lấy dữ liệu định dạng CSV")
  .option("-o, --out <file>", "Ghi đè file đầu ra (tùy chọn)")
  .action(async (options) => {
    const endpointPath = options.csv ? "/Datums/DataByDate" : "/Datums/DataByDateJson";
    const endpoint = `${endpointPath}?DeviceSerialNumber=${options.serial}&StartDate=${options.start}&EndDate=${options.end}`;
    const data = await apiFetch(endpoint, false, options.csv);
    const outFile = options.out || getAutoFilePath("interval", options.serial, options);
    outputData(data, outFile);
  });

program
  .command("all")
  .description("Thu thập toàn bộ dữ liệu từ đầu đến giờ của 1 thiết bị")
  .requiredOption("-s, --serial <serialNumber>", "SerialNumber của thiết bị")
  .option("--csv", "Lưu file CSV (mặc định json trừ khi API trả CSV)")
  .option("-o, --out <file>", "Ghi đè file đầu ra (tùy chọn)")
  .action(async (options) => {
    let data;
    let isCsv = options.csv;
    try {
      console.log("Trying /AllDataByDevice endpoint...");
      const endpoint = `/Datums/AllDataByDevice?DeviceSerialNumber=${options.serial}`;
      data = await apiFetch(endpoint, true, isCsv); // true to throw error instead of exit
    } catch (err) {
      console.log(`Failed to fetch via AllDataByDevice (${err.message}). Falling back to 7-day chunking from 2026-05-29...`);
      
      const chunks = [];
      let currentDate = new Date("2026-05-29");
      const endDate = new Date();
      
      while (currentDate <= endDate) {
        const nextDate = new Date(currentDate);
        nextDate.setDate(nextDate.getDate() + 6); // 7 day inclusive window
        
        const chunkStart = currentDate.toISOString().split("T")[0];
        const chunkEnd = (nextDate > endDate ? endDate : nextDate).toISOString().split("T")[0];
        
        chunks.push({ start: chunkStart, end: chunkEnd });
        
        currentDate = new Date(nextDate);
        currentDate.setDate(currentDate.getDate() + 1);
      }
      
      const endpointPath = isCsv ? "/Datums/DataByDate" : "/Datums/DataByDateJson";
      
      let allData = isCsv ? "" : [];
      let headerIncluded = false;
      
      for (let i = 0; i < chunks.length; i++) {
        const chunk = chunks[i];
        console.log(`⏳ Fetching chunk ${i+1}/${chunks.length}: ${chunk.start} to ${chunk.end}...`);
        const endpoint = `${endpointPath}?DeviceSerialNumber=${options.serial}&StartDate=${chunk.start}&EndDate=${chunk.end}`;
        
        try {
          const chunkData = await apiFetch(endpoint, true, isCsv);
          if (isCsv) {
            const lines = chunkData.trim().split("\n");
            if (!headerIncluded) {
              allData += chunkData;
              headerIncluded = true;
            } else if (lines.length > 1) {
              allData += "\n" + lines.slice(1).join("\n");
            }
          } else {
             if (Array.isArray(chunkData)) {
               allData = allData.concat(chunkData);
             }
          }
        } catch (e) {
          console.error(`❌ Failed to fetch chunk ${chunk.start}-${chunk.end}: ${e.message}`);
        }
      }
      data = allData;
    }

    const isString = typeof data === "string";
    const outFile = options.out || getAutoFilePath("all", options.serial, { csv: isString });
    outputData(data, outFile);
  });

program
  .command("stats")
  .description("Thống kê dữ liệu")
  .requiredOption("-s, --serial <serialNumber>", "SerialNumber của thiết bị")
  .requiredOption("--start <date>", "Ngày bắt đầu")
  .requiredOption("--end <date>", "Ngày kết thúc")
  .option("--by-sensor", "Thống kê theo sensor thay vì theo thiết bị chung")
  .option("-o, --out <file>", "Ghi đè file đầu ra (tùy chọn)")
  .action(async (options) => {
    const endpointPath = options.bySensor ? "/Datums/StatisticDataBySensor" : "/Datums/StatisticDataByDevice";
    const endpoint = `${endpointPath}?DeviceSerialNumber=${options.serial}&StartDate=${options.start}&EndDate=${options.end}`;
    const data = await apiFetch(endpoint);
    const outFile = options.out || getAutoFilePath("interval", options.serial, { start: options.start, end: `${options.end}_stats`, csv: false });
    outputData(data, outFile);
  });

program.parse(process.argv);
