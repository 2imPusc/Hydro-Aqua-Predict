require("dotenv").config({ quiet: true, path: require("path").join(__dirname, "..", ".env") });

const { MongoClient } = require("mongodb");

const MONGODB_URI = process.env.MONGODB_URI;
const DB_NAME = process.env.MONGODB_DB_NAME || "data";
const COLLECTION_NAME = process.env.MONGODB_COLLECTION_NAME || "quan_trac";

if (!MONGODB_URI) {
  console.error("Missing MONGODB_URI in .env");
  process.exit(1);
}

function formatUTC7(value) {
  if (!value) return value;

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  // Convert UTC time to UTC+7
  const utc7Date = new Date(date.getTime() + 7 * 60 * 60 * 1000);

  // Output format: 2026-05-29T13:07:19.000+07:00
  return utc7Date.toISOString().replace("Z", "+07:00");
}

function convertDatesToUTC7(value) {
  if (value instanceof Date) {
    return formatUTC7(value);
  }

  if (Array.isArray(value)) {
    return value.map(convertDatesToUTC7);
  }

  if (value && typeof value === "object") {
    // Convert MongoDB ObjectId to string
    if (value._bsontype === "ObjectId") {
      return value.toString();
    }

    const converted = {};

    for (const key of Object.keys(value)) {
      converted[key] = convertDatesToUTC7(value[key]);
    }

    return converted;
  }

  return value;
}

async function main() {
  console.log("Starting GreenLab MongoDB fetch...");
  console.log("Database:", DB_NAME);
  console.log("Collection:", COLLECTION_NAME);

  const client = new MongoClient(MONGODB_URI, {
    serverSelectionTimeoutMS: 10000,
    connectTimeoutMS: 10000,
    socketTimeoutMS: 10000,
    tls: true,
  });

  try {
    console.log("Connecting to MongoDB Atlas...");
    await client.connect();

    console.log("Connected to MongoDB Atlas.");

    const db = client.db(DB_NAME);
    const collection = db.collection(COLLECTION_NAME);

    console.log("Fetching latest document...");

    const latestDocument = await collection.findOne(
      {
        type: "greenlab_latest_snapshot",
      },
      {
        sort: {
          fetchedAt: -1,
        },
      }
    );

    if (!latestDocument) {
      console.log("No latest GreenLab snapshot document found.");
      return;
    }

    const convertedDocument = convertDatesToUTC7(latestDocument);

    console.log("Latest GreenLab snapshot document:");
    console.log(JSON.stringify(convertedDocument, null, 2));
  } catch (error) {
    console.error("Failed to fetch latest GreenLab document:");
    console.error(error.message);
    process.exit(1);
  } finally {
    await client.close();
    console.log("MongoDB connection closed.");
  }
}

main();