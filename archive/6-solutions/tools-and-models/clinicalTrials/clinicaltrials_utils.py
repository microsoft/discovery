"""
ClinicalTrials.gov Utilities Module

A comprehensive utility module for accessing the ClinicalTrials.gov database,
providing enhanced functionality for clinical trial search, metadata extraction,
and detailed study information retrieval.

This module provides high-level functions for:
- Clinical trial search with flexible filters
- Detailed study metadata extraction
- Trial status and phase information
- Eligibility criteria and enrollment data
- Results and outcomes                f"   URL: {study['url']}",
                ""
            ])
        
        report_filename = os.path.join(output_dir, "clinical_trials_report.txt")
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))hen available

Author: Microsoft Discovery ClinicalTrials Agent
Date: October 2025
"""

import json
import os
import time
import ssl
from typing import List, Dict, Optional, Any, Union
import requests
from datetime import datetime


def parse_clinical_trial_date(date_string: Optional[str], default: str = "9999-12-31") -> str:
    """
    Safely parse clinical trial dates that may be in various formats.
    
    ClinicalTrials.gov API returns dates in multiple formats:
    - "YYYY-MM-DD" (e.g., "2023-06-15") - Full date
    - "YYYY-MM" (e.g., "2023-06") - Year and month only
    - "YYYY" (e.g., "2023") - Year only
    - None or empty string
    
    Args:
        date_string: Date string from API (may be None or in various formats)
        default: Default date to return if parsing fails or date is None
        
    Returns:
        Normalized date string in "YYYY-MM-DD" format for sorting/comparison
        
    Example:
        >>> parse_clinical_trial_date("2023-06")
        "2023-06-01"
        >>> parse_clinical_trial_date("2023")
        "2023-01-01"
        >>> parse_clinical_trial_date(None)
        "9999-12-31"
    """
    if not date_string or not isinstance(date_string, str):
        return default
    
    date_string = date_string.strip()
    
    if not date_string:
        return default
    
    try:
        # Try full date format first (YYYY-MM-DD)
        if len(date_string) == 10 and date_string.count('-') == 2:
            datetime.strptime(date_string, "%Y-%m-%d")
            return date_string
        
        # Try year-month format (YYYY-MM)
        elif len(date_string) == 7 and date_string.count('-') == 1:
            datetime.strptime(date_string, "%Y-%m")
            return f"{date_string}-01"  # Normalize to first day of month
        
        # Try year only format (YYYY)
        elif len(date_string) == 4 and date_string.isdigit():
            datetime.strptime(date_string, "%Y")
            return f"{date_string}-01-01"  # Normalize to January 1st
        
        # Unknown format
        else:
            return default
            
    except (ValueError, AttributeError):
        return default


def sort_studies_by_date(studies: List[Dict[str, Any]], 
                         date_field: str = "start_date",
                         reverse: bool = False) -> List[Dict[str, Any]]:
    """
    Safely sort clinical trial studies by date field.
    
    Handles various date formats from ClinicalTrials.gov API and missing dates.
    
    Args:
        studies: List of study dictionaries
        date_field: Name of the date field to sort by (default: "start_date")
        reverse: If True, sort newest to oldest; if False, oldest to newest
        
    Returns:
        Sorted list of studies
        
    Example:
        >>> sorted_studies = sort_studies_by_date(studies, "start_date", reverse=True)
    """
    return sorted(
        studies,
        key=lambda x: parse_clinical_trial_date(x.get(date_field), "9999-12-31" if not reverse else "0000-01-01"),
        reverse=reverse
    )


def get_study_year(study: Dict[str, Any], date_field: str = "start_date") -> Optional[int]:
    """
    Extract the year from a study's date field.
    
    Safely handles all ClinicalTrials.gov date formats and returns just the year as an integer.
    
    Args:
        study: Study dictionary
        date_field: Name of the date field (default: "start_date")
        
    Returns:
        Year as integer, or None if date is not available
        
    Example:
        >>> year = get_study_year(study, "start_date")
        >>> if year and year >= 2000:
        >>>     # Process study
    """
    date_parts = get_date_parts(study.get(date_field))
    return date_parts.get("year") if date_parts else None


def get_date_parts(date_string: Optional[str]) -> Optional[Dict[str, int]]:
    """
    Extract year, month, and day as integers from a clinical trial date string.
    
    Safely handles all ClinicalTrials.gov date formats (YYYY-MM-DD, YYYY-MM, YYYY).
    
    Args:
        date_string: Date string from API (may be None or in various formats)
        
    Returns:
        Dictionary with 'year', 'month', 'day' as integers, or None if date is not available.
        Missing components (month/day) will be set to 1 as defaults.
        
    Example:
        >>> get_date_parts("2023-06-15")
        {'year': 2023, 'month': 6, 'day': 15}
        >>> get_date_parts("2023-06")
        {'year': 2023, 'month': 6, 'day': 1}
        >>> get_date_parts("2023")
        {'year': 2023, 'month': 1, 'day': 1}
        >>> get_date_parts(None)
        None
    """
    if not date_string:
        return None
    
    normalized = parse_clinical_trial_date(date_string, "9999-12-31")
    if not normalized or normalized == "9999-12-31":
        return None
    
    try:
        parts = normalized.split("-")
        if len(parts) != 3:
            return None
        
        return {
            "year": int(parts[0]),
            "month": int(parts[1]),
            "day": int(parts[2])
        }
    except (ValueError, IndexError):
        return None


def filter_studies_by_year(studies: List[Dict[str, Any]], 
                           min_year: Optional[int] = None,
                           max_year: Optional[int] = None,
                           date_field: str = "start_date") -> List[Dict[str, Any]]:
    """
    Filter studies by year range.
    
    Args:
        studies: List of study dictionaries
        min_year: Minimum year (inclusive), e.g., 2000
        max_year: Maximum year (inclusive), e.g., 2023
        date_field: Name of the date field to filter by (default: "start_date")
        
    Returns:
        Filtered list of studies
        
    Example:
        >>> # Get studies from 2000 onwards
        >>> recent_studies = filter_studies_by_year(studies, min_year=2000)
        >>> 
        >>> # Get studies from 2010 to 2020
        >>> decade_studies = filter_studies_by_year(studies, min_year=2010, max_year=2020)
    """
    filtered = []
    for study in studies:
        year = get_study_year(study, date_field)
        if year is None:
            continue
        
        if min_year is not None and year < min_year:
            continue
        
        if max_year is not None and year > max_year:
            continue
        
        filtered.append(study)
    
    return filtered


def filter_studies_by_date(studies: List[Dict[str, Any]], 
                           min_date: Optional[str] = None,
                           max_date: Optional[str] = None,
                           date_field: str = "start_date") -> List[Dict[str, Any]]:
    """
    Filter studies by full date range (year-month-day).
    
    Args:
        studies: List of study dictionaries
        min_date: Minimum date (inclusive) in "YYYY-MM-DD" format, e.g., "2020-01-01"
        max_date: Maximum date (inclusive) in "YYYY-MM-DD" format, e.g., "2023-12-31"
        date_field: Name of the date field to filter by (default: "start_date")
        
    Returns:
        Filtered list of studies
        
    Example:
        >>> # Get studies from January 2020 onwards
        >>> recent_studies = filter_studies_by_date(studies, min_date="2020-01-01")
        >>> 
        >>> # Get studies between two dates
        >>> range_studies = filter_studies_by_date(
        >>>     studies, 
        >>>     min_date="2020-01-01", 
        >>>     max_date="2023-12-31"
        >>> )
    """
    filtered = []
    for study in studies:
        date_str = study.get(date_field)
        if not date_str:
            continue
        
        normalized = parse_clinical_trial_date(date_str, "9999-12-31")
        if normalized == "9999-12-31":
            continue
        
        if min_date is not None and normalized < min_date:
            continue
        
        if max_date is not None and normalized > max_date:
            continue
        
        filtered.append(study)
    
    return filtered


# Configure SSL to handle certificate issues in containers
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass


class ClinicalTrialsUtils:
    """
    Utility class for ClinicalTrials.gov operations with enhanced functionality.
    """
    
    # ClinicalTrials.gov API v2 endpoint
    BASE_URL = "https://clinicaltrials.gov/api/v2"
    
    def __init__(self):
        """
        Initialize ClinicalTrialsUtils.
        ClinicalTrials.gov API does not require authentication.
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Microsoft-Discovery-ClinicalTrials-Agent/1.0'
        })
    
    def search_studies(self, query: str = None, condition: str = None, 
                      intervention: str = None, location: str = None,
                      status: str = None, phase: str = None,
                      strict_phase_filter: bool = False,
                      max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Search for clinical trials with flexible filters.
        
        Args:
            query: General search query (searches across all fields)
            condition: Disease or condition (e.g., "Cancer", "Diabetes")
            intervention: Treatment/intervention (e.g., "Drug X", "Surgery")
            location: Geographic location (e.g., "United States", "California")
            status: Study status (e.g., "RECRUITING", "COMPLETED", "ACTIVE_NOT_RECRUITING")
            phase: Study phase (e.g., "PHASE1", "PHASE2", "PHASE3", "PHASE4")
            strict_phase_filter: If True, only return studies with exact phase match
                                (excludes combined phases like "PHASE1, PHASE2")
            max_results: Maximum number of results to return
            
        Returns:
            List of dictionaries containing study metadata
        """
        # Build query parameters using dedicated API v2 parameters
        params = {
            "format": "json",
            "pageSize": min(max_results, 1000)  # API limit is 1000
        }

        # Use dedicated API v2 parameters for structured filters
        if query:
            params["query.term"] = query
        if condition:
            params["query.cond"] = condition
        if intervention:
            params["query.intr"] = intervention
        if location:
            params["query.locn"] = location
        if status:
            params["filter.overallStatus"] = status
        if phase:
            # Note: filter.phase is NOT a valid API v2 parameter.
            # Use filter.advanced with AREA syntax for phase filtering.
            params["filter.advanced"] = f"AREA[Phase]{phase}"
        
        try:
            # Make API request
            response = self.session.get(f"{self.BASE_URL}/studies", params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            studies = []
            
            # Extract study information
            if "studies" in data:
                for study in data["studies"]:
                    study_data = self._extract_study_metadata(study)
                    studies.append(study_data)
            
            # Apply strict phase filtering if requested
            if strict_phase_filter and phase:
                original_count = len(studies)
                
                # For PHASE1, also accept EARLY_PHASE1 as equivalent
                if phase == "PHASE1":
                    studies = [
                        s for s in studies 
                        if s.get('phase') in ['PHASE1', 'EARLY_PHASE1']
                    ]
                else:
                    # For other phases, exact match only
                    studies = [
                        s for s in studies 
                        if s.get('phase') == phase
                    ]
                
                filtered_count = len(studies)
                if original_count > filtered_count:
                    print(f"Strict phase filter: {original_count} -> {filtered_count} studies "
                          f"(removed {original_count - filtered_count} combined-phase studies)")
            
            return studies[:max_results]
            
        except requests.exceptions.RequestException as e:
            print(f"Error searching ClinicalTrials.gov: {str(e)}")
            return []
    
    def get_study_details(self, nct_id: str, verbose: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific clinical trial.
        
        Args:
            nct_id: NCT ID of the study (e.g., "NCT01234567")
            verbose: If True, print progress information to stdout
            
        Returns:
            Dictionary containing detailed study information
        """
        try:
            # Clean NCT ID
            nct_id = nct_id.strip().upper()
            if not nct_id.startswith("NCT"):
                nct_id = f"NCT{nct_id}"
            
            if verbose:
                print(f"  -> Fetching details for {nct_id}...", end=" ", flush=True)
            
            # Make API request for specific study
            # Note: /studies/{nctId} endpoint returns study data directly, 
            # not wrapped in a "studies" array like the search endpoint
            response = self.session.get(
                f"{self.BASE_URL}/studies/{nct_id}",
                params={"format": "json"},
                timeout=30
            )
            response.raise_for_status()
            
            study = response.json()
            
            # Check if we got valid study data (should have protocolSection)
            if "protocolSection" in study:
                details = self._extract_detailed_study_info(study)
                
                if verbose:
                    # Print a brief summary on the same line
                    title = details.get('title', '')[:50]
                    status = details.get('status', 'N/A')
                    print(f"OK {title}... ({status})")
                
                return details
            
            if verbose:
                print("ERROR No data found")
            return None
            
        except requests.exceptions.RequestException as e:
            if verbose:
                print(f"ERROR Error: {str(e)}")
            else:
                print(f"Error retrieving study {nct_id}: {str(e)}")
            return None
    
    def _extract_study_metadata(self, study: Dict) -> Dict[str, Any]:
        """
        Extract basic metadata from study data.
        
        Args:
            study: Raw study data from API
            
        Returns:
            Dictionary with structured metadata
        """
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        description = protocol.get("descriptionModule", {})
        conditions = protocol.get("conditionsModule", {})
        design = protocol.get("designModule", {})
        
        return {
            "nct_id": identification.get("nctId", ""),
            "title": identification.get("officialTitle") or identification.get("briefTitle", ""),
            "brief_summary": description.get("briefSummary", ""),
            "status": status.get("overallStatus", ""),
            "phase": ", ".join(design.get("phases", [])),
            "conditions": conditions.get("conditions", []),
            "enrollment": status.get("enrollmentInfo", {}).get("count"),
            "start_date": status.get("startDateStruct", {}).get("date"),
            "completion_date": status.get("completionDateStruct", {}).get("date"),
            "study_type": design.get("studyType", ""),
            "url": f"https://clinicaltrials.gov/study/{identification.get('nctId', '')}",
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date")
        }
    
    def _extract_detailed_study_info(self, study: Dict) -> Dict[str, Any]:
        """
        Extract comprehensive information from study data.
        
        Args:
            study: Raw study data from API
            
        Returns:
            Dictionary with detailed study information
        """
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        description = protocol.get("descriptionModule", {})
        conditions = protocol.get("conditionsModule", {})
        design = protocol.get("designModule", {})
        arms = protocol.get("armsInterventionsModule", {})
        eligibility = protocol.get("eligibilityModule", {})
        contacts = protocol.get("contactsLocationsModule", {})
        sponsor = protocol.get("sponsorCollaboratorsModule", {})
        
        # Extract results if available
        results = study.get("resultsSection", {})
        
        detailed_info = {
            "nct_id": identification.get("nctId", ""),
            "title": identification.get("officialTitle") or identification.get("briefTitle", ""),
            "acronym": identification.get("acronym"),
            "brief_summary": description.get("briefSummary", ""),
            "detailed_description": description.get("detailedDescription", ""),
            
            # Status information
            "status": status.get("overallStatus", ""),
            "why_stopped": status.get("whyStopped"),
            "start_date": status.get("startDateStruct", {}).get("date"),
            "completion_date": status.get("completionDateStruct", {}).get("date"),
            "last_update": status.get("lastUpdatePostDateStruct", {}).get("date"),
            
            # Study design
            "study_type": design.get("studyType", ""),
            "phase": ", ".join(design.get("phases", [])),
            "design_allocation": design.get("designInfo", {}).get("allocation"),
            "design_intervention_model": design.get("designInfo", {}).get("interventionModel"),
            "design_masking": design.get("designInfo", {}).get("maskingInfo", {}).get("masking"),
            "primary_purpose": design.get("designInfo", {}).get("primaryPurpose"),
            
            # Conditions and interventions
            "conditions": conditions.get("conditions", []),
            "keywords": conditions.get("keywords", []),
            "interventions": [
                {
                    "type": intervention.get("type"),
                    "name": intervention.get("name"),
                    "description": intervention.get("description")
                }
                for intervention in arms.get("interventions", [])
            ],
            
            # Enrollment
            "enrollment": {
                "count": status.get("enrollmentInfo", {}).get("count"),
                "type": status.get("enrollmentInfo", {}).get("type")
            },
            
            # Eligibility
            "eligibility": {
                "criteria": eligibility.get("eligibilityCriteria", ""),
                "gender": eligibility.get("sex"),
                "minimum_age": eligibility.get("minimumAge"),
                "maximum_age": eligibility.get("maximumAge"),
                "healthy_volunteers": eligibility.get("healthyVolunteers")
            },
            
            # Sponsor/Collaborators
            "sponsor": {
                "lead_sponsor": sponsor.get("leadSponsor", {}).get("name"),
                "collaborators": [c.get("name") for c in sponsor.get("collaborators", [])]
            },
            
            # Locations
            "locations": [
                {
                    "facility": loc.get("facility"),
                    "city": loc.get("city"),
                    "state": loc.get("state"),
                    "country": loc.get("country"),
                    "status": loc.get("status")
                }
                for loc in contacts.get("locations", [])
            ][:10],  # Limit to first 10 locations
            
            # Contact information
            "central_contacts": [
                {
                    "name": contact.get("name"),
                    "role": contact.get("role"),
                    "phone": contact.get("phone"),
                    "email": contact.get("email")
                }
                for contact in contacts.get("centralContacts", [])
            ],
            
            # Results (if available)
            "has_results": bool(results),
            "results_first_posted": results.get("baselineCharacteristicsModule", {}).get("populationDescription") if results else None,
            
            # URLs
            "url": f"https://clinicaltrials.gov/study/{identification.get('nctId', '')}",
            "results_url": f"https://clinicaltrials.gov/study/{identification.get('nctId', '')}/results" if results else None
        }
        
        return detailed_info
    
    def search_by_condition(self, condition: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Search for trials by medical condition.
        
        Args:
            condition: Medical condition to search for
            max_results: Maximum number of results
            
        Returns:
            List of studies related to the condition
        """
        return self.search_studies(condition=condition, max_results=max_results)
    
    def search_by_intervention(self, intervention: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Search for trials by intervention/treatment.
        
        Args:
            intervention: Intervention/treatment to search for
            max_results: Maximum number of results
            
        Returns:
            List of studies using the intervention
        """
        return self.search_studies(intervention=intervention, max_results=max_results)
    
    def search_recruiting_studies(self, condition: str = None, location: str = None, 
                                 max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Search for currently recruiting studies.
        
        Args:
            condition: Optional condition filter
            location: Optional location filter
            max_results: Maximum number of results
            
        Returns:
            List of recruiting studies
        """
        return self.search_studies(
            condition=condition,
            location=location,
            status="RECRUITING",
            max_results=max_results
        )
    
    def download_study_data(self, query: str = None, condition: str = None,
                          intervention: str = None, location: str = None,
                          status: str = None, phase: str = None,
                          strict_phase_filter: bool = False,
                          max_results: int = 20, output_dir: str = None) -> Dict[str, Any]:
        """
        Complete workflow: search for studies and download detailed information.
        
        Args:
            query: General search query
            condition: Disease or condition filter
            intervention: Treatment/intervention filter
            location: Geographic location filter
            status: Study status filter (e.g., "RECRUITING", "COMPLETED")
            phase: Study phase filter (e.g., "PHASE1", "PHASE2", "PHASE3")
            strict_phase_filter: If True, exclude combined phases (e.g., "PHASE1, PHASE2")
            max_results: Maximum number of studies to process
            output_dir: Directory to save downloaded files
            
        Returns:
            Dictionary with summary and detailed study information
        """
        # Validate output_dir is provided
        if not output_dir:
            raise ValueError("output_dir is required. Pass the output directory from dataHandlingContext.")
        # Ensure output directory exists with proper error handling
        try:
            os.makedirs(output_dir, exist_ok=True)
            # Verify directory is writable
            test_file = os.path.join(output_dir, ".test_write")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            print(f"Warning: Could not create/verify output directory {output_dir}: {e}")
            print(f"Attempting to use current directory instead")
            output_dir = "."
        
        print(f"Starting clinical trial data download...")
        print(f"Output directory: {output_dir}")
        print(f"Query: {query}, Condition: {condition}, Intervention: {intervention}")
        print(f"Location: {location}, Status: {status}, Phase: {phase}")
        if strict_phase_filter:
            print(f"Strict phase filtering: ENABLED (excludes combined phases)")
        
        # Search for studies
        studies = self.search_studies(
            query=query,
            condition=condition,
            intervention=intervention,
            location=location,
            status=status,
            phase=phase,
            strict_phase_filter=strict_phase_filter,
            max_results=max_results
        )
        
        print(f"Found {len(studies)} studies")
        
        detailed_studies = []
        
        # Get detailed information for each study
        print(f"\nDownloading detailed information for {len(studies)} studies...")
        print("This may take several minutes. Please wait...\n")
        
        for i, study in enumerate(studies, 1):
            nct_id = study.get("nct_id")
            if not nct_id:
                continue
            
            print(f"[{i}/{len(studies)}] {nct_id}: ", end="", flush=True)
            
            # Get detailed information (verbose=True will print on the same line)
            detailed_info = self.get_study_details(nct_id, verbose=True)
            
            if detailed_info:
                detailed_studies.append(detailed_info)
                
                # Save individual study file
                try:
                    study_filename = os.path.join(output_dir, f"study_{nct_id}_details.json")
                    with open(study_filename, "w", encoding="utf-8") as f:
                        json.dump(detailed_info, f, indent=2)
                except Exception as e:
                    print(f"  Warning: Could not save individual study file: {e}")
            
            # Rate limiting - be nice to the API
            time.sleep(0.5)
        
        # Create summary
        summary = {
            "search_parameters": {
                "query": query,
                "condition": condition,
                "intervention": intervention,
                "location": location,
                "status": status,
                "phase": phase,
                "max_results": max_results
            },
            "search_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_studies_found": len(studies),
            "studies_with_details": len(detailed_studies),
            "summary_data": studies,  # Basic info for all studies
            "detailed_data": detailed_studies  # Full details
        }
        
        # Save comprehensive results
        try:
            summary_filename = os.path.join(output_dir, "clinical_trials_summary.json")
            with open(summary_filename, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save summary file: {e}")
        
        # Create readable report
        try:
            self._create_study_report(summary, detailed_studies, output_dir)
        except Exception as e:
            print(f"Warning: Could not create report: {e}")
        
        print(f"\nDownload complete! Processed {len(detailed_studies)} studies")
        
        return summary
    
    def _create_study_report(self, summary: Dict[str, Any], studies: List[Dict[str, Any]], 
                           output_dir: str):
        """
        Create a human-readable study report.
        
        Args:
            summary: Summary statistics
            studies: List of detailed studies
            output_dir: Output directory
        """
        report_lines = [
            "Clinical Trials Data Report",
            "=" * 50,
            f"Search Date: {summary['search_date']}",
            f"Query: {summary['search_parameters'].get('query', 'N/A')}",
            f"Condition: {summary['search_parameters'].get('condition', 'N/A')}",
            f"Intervention: {summary['search_parameters'].get('intervention', 'N/A')}",
            f"Total Studies Found: {summary['total_studies_found']}",
            "",
            "Study Details:",
            "-" * 50
        ]
        
        for i, study in enumerate(studies, 1):
            report_lines.extend([
                f"\n{i}. {study['title']}",
                f"   NCT ID: {study['nct_id']}",
                f"   Status: {study['status']}",
                f"   Phase: {study.get('phase', 'N/A')}",
                f"   Conditions: {', '.join(study.get('conditions', [])[:3])}",
                f"   Enrollment: {study.get('enrollment', {}).get('count', 'N/A')}",
                f"   URL: {study['url']}",
                ""
            ])
        
        report_filename = f"{output_dir}/clinical_trials_report.txt"
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    
    # Helper methods for date handling (delegates to module-level functions)
    def sort_studies_by_date(self, studies: List[Dict[str, Any]], 
                            date_field: str = "start_date",
                            reverse: bool = False) -> List[Dict[str, Any]]:
        """
        Sort clinical trial studies by date field.
        
        Args:
            studies: List of study dictionaries
            date_field: Name of the date field to sort by (default: "start_date")
            reverse: If True, sort newest to oldest; if False, oldest to newest
            
        Returns:
            Sorted list of studies
        """
        return sort_studies_by_date(studies, date_field, reverse)
    
    def filter_studies_by_year(self, studies: List[Dict[str, Any]], 
                              min_year: Optional[int] = None,
                              max_year: Optional[int] = None,
                              date_field: str = "start_date") -> List[Dict[str, Any]]:
        """
        Filter studies by year range.
        
        Args:
            studies: List of study dictionaries
            min_year: Minimum year (inclusive), e.g., 2000
            max_year: Maximum year (inclusive), e.g., 2023
            date_field: Name of the date field to filter by (default: "start_date")
            
        Returns:
            Filtered list of studies
        """
        return filter_studies_by_year(studies, min_year, max_year, date_field)
    
    def filter_studies_by_date(self, studies: List[Dict[str, Any]], 
                              min_date: Optional[str] = None,
                              max_date: Optional[str] = None,
                              date_field: str = "start_date") -> List[Dict[str, Any]]:
        """
        Filter studies by full date range (year-month-day).
        
        Args:
            studies: List of study dictionaries
            min_date: Minimum date (inclusive) in "YYYY-MM-DD" format
            max_date: Maximum date (inclusive) in "YYYY-MM-DD" format
            date_field: Name of the date field to filter by (default: "start_date")
            
        Returns:
            Filtered list of studies
        """
        return filter_studies_by_date(studies, min_date, max_date, date_field)


# Convenience functions for direct usage
def search_clinical_trials(query: str = None, condition: str = None,
                          intervention: str = None, location: str = None,
                          status: str = None, phase: str = None,
                          strict_phase_filter: bool = False,
                          max_results: int = 20) -> List[Dict[str, Any]]:
    """
    Convenience function to search clinical trials.

    Args:
        query: General search query
        condition: Disease or condition
        intervention: Treatment/intervention
        location: Geographic location (e.g., "United States", "California")
        status: Study status (e.g., "RECRUITING", "COMPLETED")
        phase: Study phase (e.g., "PHASE1", "PHASE2", "PHASE3")
        strict_phase_filter: If True, exclude combined phases
        max_results: Maximum number of results

    Returns:
        List of studies
    """
    utils = ClinicalTrialsUtils()
    return utils.search_studies(query=query, condition=condition,
                               intervention=intervention, location=location,
                               status=status, phase=phase,
                               strict_phase_filter=strict_phase_filter,
                               max_results=max_results)


def get_study_details(nct_id: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get detailed study information.
    
    Args:
        nct_id: NCT ID of the study
        
    Returns:
        Detailed study information
    """
    utils = ClinicalTrialsUtils()
    return utils.get_study_details(nct_id)


def download_trial_data(query: str = None, condition: str = None,
                       intervention: str = None, location: str = None,
                       status: str = None, phase: str = None,
                       strict_phase_filter: bool = False,
                       max_results: int = 20,
                       output_dir: str = "/output") -> Dict[str, Any]:
    """
    Convenience function to download trial data.

    Args:
        query: General search query
        condition: Disease or condition
        intervention: Treatment/intervention
        location: Geographic location
        status: Study status (e.g., "RECRUITING", "COMPLETED")
        phase: Study phase (e.g., "PHASE1", "PHASE2", "PHASE3")
        strict_phase_filter: If True, exclude combined phases (e.g., "PHASE1, PHASE2")
        max_results: Maximum number of results
        output_dir: Directory to save downloaded files (default: "/output")

    Returns:
        Summary of downloaded data
    """
    utils = ClinicalTrialsUtils()
    return utils.download_study_data(query=query, condition=condition,
                                    intervention=intervention, location=location,
                                    status=status, phase=phase,
                                    strict_phase_filter=strict_phase_filter,
                                    max_results=max_results,
                                    output_dir=output_dir)
