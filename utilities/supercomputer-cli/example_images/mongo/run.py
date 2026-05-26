#!/usr/bin/env python3
"""
Python script that connects to MongoDB using environment variables.
"""

import os
import sys
import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_mongo_connection():
    """
    Establish connection to MongoDB using environment variables.
    
    Expected environment variables:
    - MONGO_URI: Full MongoDB connection string (preferred)
    OR
    - MONGO_HOST: MongoDB host (default: localhost)
    - MONGO_PORT: MongoDB port (default: 27017)
    - MONGO_DB: Database name (default: test)
    - MONGO_USERNAME: Username (optional)
    - MONGO_PASSWORD: Password (optional)
    """
    
    # Try to get full URI first
    mongo_uri = os.getenv('MONGO_URI')
    
    if mongo_uri:
        logger.info("Using MONGO_URI for connection")
        connection_string = mongo_uri
    else:
        # Build connection string from individual components
        host = os.getenv('MONGO_HOST', 'localhost')
        port = os.getenv('MONGO_PORT', '27017')
        username = os.getenv('MONGO_USERNAME')
        password = os.getenv('MONGO_PASSWORD')
        
        if username and password:
            connection_string = f"mongodb://{username}:{password}@{host}:{port}/"
        else:
            connection_string = f"mongodb://{host}:{port}/"
        
        logger.info(f"Built connection string for {host}:{port}")
    
    try:
        # Create MongoDB client
        client = MongoClient(
            connection_string,
            serverSelectionTimeoutMS=5000,  # 5 second timeout
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        
        # Test the connection
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        return client
        
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error connecting to MongoDB: {e}")
        return None

def main():
    """Main function to demonstrate MongoDB connection and basic operations."""
    
    logger.info("Starting MongoDB connection script...")
    
    # Get MongoDB connection
    client = get_mongo_connection()
    
    if not client:
        logger.error("Could not establish MongoDB connection. Exiting.")
        sys.exit(1)
    
    try:
        # Get database name from environment or use default
        db_name = os.getenv('MONGO_DB', 'test')
        db = client[db_name]
        
        logger.info(f"Connected to database: {db_name}")
        
        # List available collections
        collections = db.list_collection_names()
        logger.info(f"Available collections: {collections}")
        
        # Example: Insert a test document
        test_collection = db['test_collection']
        
        # Insert a sample document
        sample_doc = {
            'timestamp': time.time(),
            'message': 'Hello from containerized Python app!',
            'status': 'running'
        }
        
        result = test_collection.insert_one(sample_doc)
        logger.info(f"Inserted document with ID: {result.inserted_id}")
        
        # Query the document back
        retrieved_doc = test_collection.find_one({'_id': result.inserted_id})
        logger.info(f"Retrieved document: {retrieved_doc}")
        
        # Keep the script running (useful for containerized environments)
        logger.info("Script running successfully. Press Ctrl+C to stop.")
        
        try:
            while True:
                # Perform periodic health check
                client.admin.command('ping')
                logger.info("MongoDB connection is healthy")
                time.sleep(30)  # Wait 30 seconds before next check
                
        except KeyboardInterrupt:
            logger.info("Received interrupt signal. Shutting down gracefully...")
            
    except Exception as e:
        logger.error(f"Error during operation: {e}")
        sys.exit(1)
        
    finally:
        if client:
            client.close()
            logger.info("MongoDB connection closed")

if __name__ == "__main__":
    main()