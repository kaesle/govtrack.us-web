"""
Parser of roll call votes
"""
from lxml import etree
import glob
import re
import logging

from parser.progress import Progress
from parser.processor import XmlProcessor
from person.models import Person, PersonRole
from person.types import RoleType
from parser.models import File
from bill.models import Bill, BillType, Amendment, AmendmentType
from vote.models import (Vote, VoteOption, VoteSource, Voter,
                         CongressChamber, VoteCategory, VoterType)

from django.template.defaultfilters import truncatewords

log = logging.getLogger('parser.vote_parser')

class VoteProcessor(XmlProcessor):
    """
    Parser of /roll records.
    """

    REQUIRED_ATTRIBUTES = ['source', 'datetime']
    ATTRIBUTES = ['source', 'datetime']
    REQUIRED_NODES = ['type', 'question', 'required', 'result']
    NODES = ['type', 'question', 'required', 'result', 'category']
    FIELD_MAPPING = {'datetime': 'created', 'type': 'vote_type'}
    SOURCE_MAPPING = {
        'senate.gov': VoteSource.senate,
        'house.gov': VoteSource.house,
        'keithpoole': VoteSource.keithpoole,
    }
    DEFAULT_VALUES = {'category': 'other'}
    CATEGORY_MAPPING = {
        'amendment': VoteCategory.amendment,
        'passage-suspension': VoteCategory.passage_suspension,
        'passage': VoteCategory.passage,
        'cloture': VoteCategory.cloture,
        'passage-part': VoteCategory.passage_part,
        'nomination': VoteCategory.nomination,
        'procedural': VoteCategory.procedural,
        'other': VoteCategory.other,
        'unknown': VoteCategory.unknown,
        'treaty': VoteCategory.ratification,
        'veto-override': VoteCategory.veto_override,
        'conviction': VoteCategory.conviction,
        'quorum': VoteCategory.procedural,
        'leadership': VoteCategory.procedural,
        'recommit': VoteCategory.procedural,
    }

    def category_handler(self, value):
        return self.CATEGORY_MAPPING[value]

    def source_handler(self, value):
        return self.SOURCE_MAPPING[value]

    def datetime_handler(self, value):
        return self.parse_datetime(value)

class VoteOptionProcessor(XmlProcessor):
    "Parser of /roll/option nodes"

    REQUIRED_ATTRIBUTES = ['key']
    ATTRIBUTES = ['key']

    def process_text(self, obj, node):
        obj.value = node.text


class VoterProcessor(XmlProcessor):
    "Parser of /roll/voter nodes"

    REQUIRED_ATTRIBUTES = ['id', 'vote']
    ATTRIBUTES = ['id', 'vote']
    FIELD_MAPPING = {'id': 'person', 'vote': 'option'}
    PERSON_CACHE = {}

    def process(self, options, obj, node):
        self.options = options
        obj = super(VoterProcessor, self).process(obj, node)

        if node.get('VP') == '1':
            obj.voter_type = VoterType.vice_president
        elif node.get('id') == '0':
            obj.voter_type = VoterType.unknown
        else:
            obj.voter_type = VoterType.member

        return obj


    def id_handler(self, value):
        if int(value):
            return self.PERSON_CACHE[int(value)]
        else:
            return None

    def vote_handler(self, value):
        return self.options[value]


def main(options):
    """
    Parse rolls.
    """
    
    # Setup XML processors
    vote_processor = VoteProcessor()
    option_processor = VoteOptionProcessor()
    voter_processor = VoterProcessor()
    voter_processor.PERSON_CACHE = dict((x.pk, x) for x in Person.objects.all())

    # The pattern which the roll file matches
    # Filename contains info which should be placed to DB
    # along with info extracted from the XML file
    re_path = re.compile('data/us/(\d+)/rolls/([hs])(\w+)-(\d+)\.xml')

    chamber_mapping = {'s': CongressChamber.senate,
                       'h': CongressChamber.house}

    if options.filter:
        files = glob.glob(options.filter)
        log.info('Parsing rolls matching %s' % options.filter)
    elif options.congress:
        files = glob.glob('data/us/%s/rolls/*.xml' % options.congress)
        log.info('Parsing rolls of only congress#%s' % options.congress)
    else:
        files = glob.glob('data/us/*/rolls/*.xml')
    log.info('Processing votes: %d files' % len(files))
    total = len(files)
    progress = Progress(total=total, name='files', step=10)

    def log_delete_qs(qs):
        if qs.count() > 0:
            try:
                print "Deleting: ", qs
            except Exception as e:
                print "Deleting [%s]..." % str(e)
            if qs.count() > 3:
                print "Delete skipped..."
                return
            qs.delete()

    seen_obj_ids = set()
    had_error = False

    for fname in files:
        progress.tick()

        match = re_path.search(fname)
        
        try:
            existing_vote = Vote.objects.get(congress=match.group(1), chamber=chamber_mapping[match.group(2)], session=match.group(3), number=match.group(4))
        except Vote.DoesNotExist:
            existing_vote = None
        
        if not File.objects.is_changed(fname) and not options.force and existing_vote != None and not existing_vote.missing_data:
            seen_obj_ids.add(existing_vote.id)
            continue
            
        try:
            tree = etree.parse(fname)
            
            ## Look for votes with VP tie breakers.
            #if len(tree.xpath("/roll/voter[@VP='1']")) == 0:
            #    had_error = True # prevent delete at the end
            #    continue
            
            # Process role object
            for roll_node in tree.xpath('/roll'):
                vote = vote_processor.process(Vote(), roll_node)
                if existing_vote: vote.id = existing_vote.id
                match = re_path.search(fname)
                vote.congress = int(match.group(1))
                vote.chamber = chamber_mapping[match.group(2)]
                vote.session = match.group(3)
                vote.number = int(match.group(4))
                
                # Get related bill & amendment.
                
                for bill_node in roll_node.xpath("bill"):
                    try:
                        vote.related_bill = Bill.objects.get(congress=bill_node.get("session"), bill_type=BillType.by_xml_code(bill_node.get("type")), number=bill_node.get("number"))
                    except Bill.DoesNotExist:
                        vote.missing_data = True

                for amdt_node in roll_node.xpath("amendment"):
                    if amdt_node.get("ref") == "regular":
                        try:
                            vote.related_amendment = Amendment.objects.get(congress=vote.related_bill.congress, amendment_type=AmendmentType.by_slug(amdt_node.get("number")[0]), number=amdt_node.get("number")[1:])
                        except Amendment.DoesNotExist:
                            print "Missing amendment", fname
                            vote.missing_data = True
                    elif amdt_node.get("ref") == "bill-serial":
                        # It is impossible to associate House votes with amendments just from the House
                        # vote XML because the amendment-num might correspond either with the A___ number
                        # or with the "An amendment, numbered ____" number from the amendment purpose,
                        # and there's really no way to figure out which. Maybe we can use the amendment
                        # sponsor instead?
                        #vote.related_amendment = Amendment.objects.get(bill=vote.related_bill, sequence=amdt_node.get("number"))
                        # Instead, we set related_amendment from the amendment parser. Here, we have to
                        # preserve the related_amendment if it is set.
                        if existing_vote: vote.related_amendment = existing_vote.related_amendment

                # clean up some question text and use the question_details field
                
                if vote.category in (VoteCategory.passage, VoteCategory.passage_suspension, VoteCategory.veto_override) and vote.related_bill:
                    # For passage votes, set the question to the bill title and put the question
                    # details in the details field.
                    vote.question = truncatewords(vote.related_bill.title, 20)
                    vote.question_details = vote.vote_type + " in the " + vote.get_chamber_display()
                    
                elif vote.category == VoteCategory.amendment and vote.related_amendment:
                    # For votes on amendments, make a better title/explanation.
                    vote.question = truncatewords(vote.related_amendment.title, 20)
                    vote.question_details = vote.vote_type + " in the " + vote.get_chamber_display()
                    
                elif vote.related_bill and vote.question.startswith("On the Cloture Motion " + vote.related_bill.display_number):
                    vote.question = "Cloture on " + truncatewords(vote.related_bill.title, 20)
                elif vote.related_bill and vote.question.startswith("On Cloture on the Motion to Proceed " + vote.related_bill.display_number):
                    vote.question = "Cloture on " + truncatewords(vote.related_bill.title, 20)
                    vote.question_details = "On Cloture on the Motion to Proceed in the " + vote.get_chamber_display()
                elif vote.related_bill and vote.question.startswith("On the Motion to Proceed " + vote.related_bill.display_number):
                    vote.question = "Motion to Proceed on " + truncatewords(vote.related_bill.title, 20)
                    
                elif vote.related_amendment and vote.question.startswith("On the Cloture Motion " + vote.related_amendment.get_amendment_type_display() + " " + str(vote.related_amendment.number)):
                    vote.question = "Cloture on " + truncatewords(vote.related_amendment.title, 20)
                    vote.question_details = vote.vote_type + " in the " + vote.get_chamber_display()
                
                # weird House foratting of bill numbers ("H RES 123 Blah blah")
                if vote.related_bill:
                    vote.question = re.sub(
                        "(On [^:]+): " + vote.related_bill.display_number.replace(". ", " ").replace(".", " ").upper() + " .*",
                        r"\1: " + truncatewords(vote.related_bill.title, 15),
                        vote.question)
                    
                vote.save()
                
                seen_obj_ids.add(vote.id) # don't delete me later
                
                # Process roll options, overwrite existing options where possible.
                seen_option_ids = set()
                roll_options = {}
                for option_node in roll_node.xpath('./option'):
                    option = option_processor.process(VoteOption(), option_node)
                    option.vote = vote
                    if existing_vote:
                        try:
                            option.id = VoteOption.objects.filter(vote=vote, key=option.key)[0].id # get is better, but I had the database corruption problem
                        except IndexError:
                            pass
                    option.save()
                    roll_options[option.key] = option
                    seen_option_ids.add(option.id)
                log_delete_qs(VoteOption.objects.filter(vote=vote).exclude(id__in=seen_option_ids)) # may cascade and delete the Voters too?

                # Process roll voters, overwriting existing voters where possible.
                if existing_vote:
                    existing_voters = dict(Voter.objects.filter(vote=vote).values_list("person", "id"))
                seen_voter_ids = set()
                for voter_node in roll_node.xpath('./voter'):
                    voter = voter_processor.process(roll_options, Voter(), voter_node)
                    voter.vote = vote
                    voter.created = vote.created
                        
                    # for VP votes, load the actual person...
                    if voter.voter_type == VoterType.vice_president:
                        try:
                            r = PersonRole.objects.get(role_type=RoleType.vicepresident, startdate__lte=vote.created, enddate__gte=vote.created)
                            voter.person = r.person
                        except:
                            # overlapping roles? missing data?
                            log.error('Could not resolve vice president in %s' % fname, exc_info=ex)
                        
                    if existing_vote and voter.person:
                        try:
                            voter.id = existing_voters[voter.person.id]
                        except KeyError:
                            pass
                        
                    voter.save()
                    
                    if voter.voter_type == VoterType.unknown and not vote.missing_data:
                        vote.missing_data = True
                        vote.save()
                        
                    seen_voter_ids.add(voter.id)
                    
                log_delete_qs(Voter.objects.filter(vote=vote).exclude(id__in=seen_voter_ids)) # possibly already deleted by cascade above

                vote.calculate_totals()

                if not options.disable_events:
                    vote.create_event()
                    
            File.objects.save_file(fname)

        except Exception, ex:
            log.error('Error in processing %s' % fname, exc_info=ex)
            had_error = True
        
    # delete vote objects that are no longer represented on disk
    if options.congress and not options.filter and not had_error:
        log_delete_qs(Vote.objects.filter(congress=options.congress).exclude(id__in = seen_obj_ids))

if __name__ == '__main__':
    main()
