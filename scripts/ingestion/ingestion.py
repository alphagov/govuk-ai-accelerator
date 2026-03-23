import sys
import argparse
from scripts.ingestion.commands.utils import load_config, get_logger
from scripts.ingestion.commands import download_content, extract_content, clean_content

def main():
    parser = argparse.ArgumentParser(description="GOV.UK Ingestion Pipeline CLI")
    parser.add_argument("step", choices=["download", "extract", "clean", "all"], help="The step to run")
    parser.add_argument("--config", help="Path to config.ini", default="scripts/ingestion/config.ini")
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(config_path=args.config)
    
    # Initialize logger
    logger = get_logger(log_path=config.temp_log_path)
    
    try:
        if args.step == "download" or args.step == "all":
            download_content(config)
            
        if args.step == "extract" or args.step == "all":
            extract_content(config)
            
        if args.step == "clean" or args.step == "all":
            clean_content(config)
            
        logger.info(f"✅ Step {args.step} completed successfully.")
        
    except Exception as e:
        logger.error(f"❌ Step {args.step} failed: {e}")
        sys.exit(1)
        
    finally:
        # For CLI, we might want to move the log here too, or just let it stay in /tmp
        # In this simple CLI, we'll just inform the user
        print(f"DEBUG: Local log staged at {config.temp_log_path}")

if __name__ == "__main__":
    main()
