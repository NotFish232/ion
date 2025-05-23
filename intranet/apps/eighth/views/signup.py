import datetime
import logging
import time

from django import http
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from prometheus_client import Summary

from ....utils.date import get_date_range_this_year
from ....utils.helpers import is_entirely_digit
from ....utils.locking import lock_on
from ....utils.serialization import safe_json
from ...auth.decorators import deny_restricted, eighth_admin_required
from ..exceptions import SignupException
from ..models import EighthActivity, EighthBlock, EighthScheduledActivity, EighthSignup, EighthWaitlist
from ..serializers import EighthBlockDetailSerializer

logger = logging.getLogger(__name__)

eighth_signup_visits = Summary("intranet_eighth_signup_visits", "Visits to the eighth signup view")
eighth_signup_submits = Summary("intranet_eighth_signup_submits", "Number of eighth period signups performed from the eighth signup view")


@login_required
@deny_restricted
def eighth_signup_view(request, block_id=None):
    start_time = time.time()

    if block_id is None and "block" in request.GET:
        block_ids = request.GET.getlist("block")
        if len(block_ids) > 1:
            return redirect("/eighth/signup/multi?{}".format(request.META["QUERY_STRING"]))

        block_id = request.GET.get("block")
        args = ""
        if "user" in request.GET:
            args = "?user={}".format(request.GET.get("user"))
        return redirect(f"/eighth/signup/{block_id}{args}")

    if request.method == "POST":
        if "unsignup" in request.POST and "aid" not in request.POST:
            uid = request.POST.get("uid")
            bid = request.POST.get("bid")
            force = request.POST.get("force") == "true" and request.user.is_eighth_admin

            if not request.user.is_eighth_admin:
                if uid != request.user.id:
                    return http.HttpResponseNotFound()

            try:
                user = get_user_model().objects.get(id=uid)
            except get_user_model().DoesNotExist:
                return http.HttpResponseNotFound("Given user does not exist.")

            try:
                eighth_signup = EighthSignup.objects.get(scheduled_activity__block__id=bid, user__id=uid)
                success_message = eighth_signup.remove_signup(request.user, force)
            except EighthSignup.DoesNotExist:
                return http.HttpResponse("The signup did not exist.")
            except SignupException as e:
                show_admin_messages = request.user.is_eighth_admin and not request.user.is_student
                return e.as_response(admin=show_admin_messages)

            return http.HttpResponse(success_message)

        for field in ("uid", "bid", "aid"):
            if not (field in request.POST and is_entirely_digit(request.POST[field])):
                return http.HttpResponseBadRequest(field + " must be an integer")

        uid = request.POST["uid"]
        bid = request.POST["bid"]
        aid = request.POST["aid"]

        try:
            user = get_user_model().objects.get(id=uid)
        except get_user_model().DoesNotExist:
            return http.HttpResponseNotFound("Given user does not exist.")

        try:
            scheduled_activity = EighthScheduledActivity.objects.exclude(activity__deleted=True).exclude(cancelled=True).get(block=bid, activity=aid)

        except EighthScheduledActivity.DoesNotExist:
            return http.HttpResponseNotFound("Given activity not scheduled for given block.")

        try:
            success_message = scheduled_activity.add_user(user, request)
        except SignupException as e:
            show_admin_messages = request.user.is_eighth_admin and not request.user.is_student
            return e.as_response(admin=show_admin_messages)

        eighth_signup_submits.observe(time.time() - start_time)

        return http.HttpResponse(success_message)
    else:
        #######
        if settings.ENABLE_HYBRID_EIGHTH and not request.user.is_eighth_admin:
            block = None
            if block_id is None:
                now = timezone.localtime()
                if now.hour < 17:
                    now = now.replace(hour=0, minute=0, second=0, microsecond=0)
                surrounding_blocks = EighthBlock.objects.exclude(
                    eighthscheduledactivity__in=EighthScheduledActivity.objects.filter(activity__name="z - Hybrid Sticky", members__in=[request.user])
                ).order_by("date", "block_letter")
                future_block = surrounding_blocks.filter(date__gte=now).first()
                if future_block is not None:
                    block = future_block
                elif surrounding_blocks is not None:
                    block = surrounding_blocks.last()
                if block is not None:
                    block_id = block.id
        #######
        else:
            block = None
            if block_id is None:
                next_block = EighthBlock.objects.get_first_upcoming_block()
                if next_block is not None:
                    block = next_block
                    block_id = next_block.id
                else:
                    last_block = EighthBlock.objects.order_by("date").last()
                    if last_block is not None:
                        block = last_block
                        block_id = last_block.id

        if "user" in request.GET and request.user.is_eighth_admin:
            try:
                user = get_user_model().objects.get(id=request.GET["user"])
            except (get_user_model().DoesNotExist, ValueError) as e:
                raise http.Http404 from e
        elif request.user.is_student:
            user = request.user
        else:
            return redirect("eighth_admin_dashboard")

        if block is None:
            try:
                block = EighthBlock.objects.prefetch_related("eighthscheduledactivity_set").get(id=block_id)
            except EighthBlock.DoesNotExist as e:
                if not EighthBlock.objects.exists():
                    # No blocks have been added yet
                    return render(request, "eighth/signup.html", {"no_blocks": True})
                else:
                    # The provided block_id is invalid
                    raise http.Http404 from e

        #######
        surrounding_blocks = []
        if settings.ENABLE_HYBRID_EIGHTH and not request.user.is_eighth_admin:
            date_start, date_end = get_date_range_this_year()
            surrounding_blocks = (
                EighthBlock.objects.exclude(
                    eighthscheduledactivity__in=EighthScheduledActivity.objects.filter(activity__name="z - Hybrid Sticky", members__in=[request.user])
                )
                .order_by("date", "block_letter")
                .filter(date__gte=date_start, date__lte=date_end)
            )
        else:
            #######
            surrounding_blocks = EighthBlock.objects.get_blocks_this_year()

        schedule = []

        signups = EighthSignup.objects.filter(user=user).select_related("scheduled_activity", "scheduled_activity__activity")
        block_signup_map = {s.scheduled_activity.block_id: s.scheduled_activity for s in signups}

        if settings.ENABLE_WAITLIST:
            waitlists = EighthWaitlist.objects.filter(user=user).select_related("scheduled_activity__activity")
        else:
            waitlists = EighthWaitlist.objects.none()
        block_waitlist_map = {w.scheduled_activity.block_id: w.scheduled_activity for w in waitlists}

        today = timezone.localdate()

        for b in surrounding_blocks:
            info = {
                "id": b.id,
                "title": b,
                "block_letter": b.block_letter,
                "block_letter_width": (len(b.block_letter) - 1) * 6 + 15,
                "current_signup": getattr(block_signup_map.get(b.id, {}), "activity", None),
                "current_signup_cancelled": getattr(block_signup_map.get(b.id, {}), "cancelled", False),
                "current_waitlist": getattr(block_waitlist_map.get(b.id, {}), "activity", None),
                "within_few_days": b.date >= today and b.date <= today + datetime.timedelta(days=2),
                "locked": b.locked,
            }

            #######
            if settings.ENABLE_HYBRID_EIGHTH:
                info.update({"block_letter": b.hybrid_text, "block_letter_width": (len(b.hybrid_text) - 1) * 6 + 15})
            #######

            if schedule and schedule[-1]["date"] == b.date:
                schedule[-1]["blocks"].append(info)
            else:
                day = {}
                day["date"] = b.date
                day["blocks"] = []
                day["blocks"].append(info)
                schedule.append(day)

        serializer_context = {"request": request, "user": user}
        block_info = EighthBlockDetailSerializer(block, context=serializer_context).data
        block_info["schedule"] = schedule

        try:
            active_block_current_signup = block_signup_map[int(block_id)].activity.id
        except KeyError:
            active_block_current_signup = None

        context = {
            "user": user,
            "real_user": request.user,
            "block_info": block_info,
            "activities_list": safe_json(block_info["activities"]),
            "active_block": block,
            "active_block_current_signup": active_block_current_signup,
        }

        #######
        if settings.ENABLE_HYBRID_EIGHTH:
            context.update({"hybrid": True})
        #######

        eighth_signup_visits.observe(time.time() - start_time)

        return render(request, "eighth/signup.html", context)


@login_required
@deny_restricted
def eighth_multi_signup_view(request):
    if request.method == "POST":
        if "unsignup" in request.POST and "aid" not in request.POST:
            uid = request.POST.get("uid")
            bids_comma = request.POST.get("bid")
            force = request.POST.get("force") == "true" and request.user.is_eighth_admin

            if not request.user.is_eighth_admin:
                if uid != request.user.id:
                    return http.HttpResponseNotFound()

            bids = bids_comma.split(",")

            try:
                user = get_user_model().objects.get(id=uid)
            except get_user_model().DoesNotExist:
                return http.HttpResponseNotFound("Given user does not exist.")

            display_messages = []
            status = 200
            for bid in bids:
                try:
                    btxt = EighthBlock.objects.get(id=bid).short_text
                except EighthBlock.DoesNotExist:
                    return http.HttpResponse(f"{bid}: Block did not exist.", status=403)
                except ValueError:
                    return http.HttpResponse(f"{bid}: Invalid block ID.", status=403)

                try:
                    eighth_signup = EighthSignup.objects.get(scheduled_activity__block__id=bid, user__id=uid)
                    success_message = eighth_signup.remove_signup(request.user, force, request.session.get("disable_waitlist_transactions", False))
                except EighthSignup.DoesNotExist:
                    status = 403
                    display_messages.append(f"{btxt}: Signup did not exist.")

                except SignupException as e:
                    show_admin_messages = request.user.is_eighth_admin and not request.user.is_student
                    resp = e.as_response(admin=show_admin_messages)
                    status = 403
                    display_messages.append(f"{btxt}: {resp.content}")

                except Exception:
                    display_messages.append(f"{btxt}: Unknown error.")

                else:
                    display_messages.append(f"{btxt}: {success_message}")

            return http.HttpResponse("\n".join(display_messages), status=status)

        for field in ("uid", "aid"):
            if not (field in request.POST and is_entirely_digit(request.POST[field])):
                return http.HttpResponseBadRequest(field + " must be an integer")

        uid = request.POST["uid"]
        bids_comma = request.POST["bid"]
        aid = request.POST["aid"]

        bids = bids_comma.split(",")

        try:
            user = get_user_model().objects.get(id=uid)
        except get_user_model().DoesNotExist:
            return http.HttpResponseNotFound("Given user does not exist.")

        display_messages = []
        status = 200
        for bid in bids:
            try:
                btxt = EighthBlock.objects.get(id=bid).short_text
            except EighthBlock.DoesNotExist:
                return http.HttpResponse(f"{bid}: Block did not exist.", status=403)
            try:
                scheduled_activity = (
                    EighthScheduledActivity.objects.exclude(activity__deleted=True).exclude(cancelled=True).get(block=bid, activity=aid)
                )

            except EighthScheduledActivity.DoesNotExist:
                display_messages.append(f"{btxt}: Activity was not scheduled for block")
            else:
                try:
                    success_message = scheduled_activity.add_user(user, request)
                except SignupException as e:
                    show_admin_messages = request.user.is_eighth_admin and not request.user.is_student
                    resp = e.as_response(admin=show_admin_messages)
                    status = 403
                    display_messages.append(f"{btxt}: {resp.content}")
                else:
                    display_messages.append(f"{btxt}: {success_message}")

        return http.HttpResponse("<br>".join(display_messages), status=status)
    else:
        if "user" in request.GET and request.user.is_eighth_admin:
            try:
                user = get_user_model().objects.get(id=request.GET["user"])
            except (get_user_model().DoesNotExist, ValueError) as e:
                raise http.Http404 from e
        elif request.user.is_student:
            user = request.user
        else:
            return redirect("eighth_admin_dashboard")

        block_ids = list(filter(None, request.GET.getlist("block")))
        try:
            blocks = EighthBlock.objects.select_related().filter(id__in=block_ids)
        except EighthBlock.DoesNotExist as e:
            raise http.Http404 from e

        serializer_context = {"request": request, "user": user}
        blocks_info = []
        block_signups = []
        activities = {}
        for block in blocks:
            try:
                signup = EighthSignup.objects.get(user=user, scheduled_activity__block=block)
            except EighthSignup.DoesNotExist:
                signup = False

            block_signups.append({"block": block, "signup": signup})

            block_info = EighthBlockDetailSerializer(block, context=serializer_context).data
            blocks_info.append(block_info)
            acts = block_info["activities"]
            for a in acts:
                info = {
                    "id": block.id,
                    "date": block.date,
                    "date_text": block.date.strftime("%a, %b %-d, %Y"),
                    "block_letter": block.block_letter,
                    "short_text": block.short_text,
                }
                if a in activities:
                    activities[a]["blocks"].append(info)
                else:
                    activities[a] = acts[a]
                    activities[a]["blocks"] = [info]
                    activities[a]["total_num_blocks"] = len(blocks)

        context = {
            "user": user,
            "profile_user": user,
            "real_user": request.user,
            "activities_list": safe_json(activities),
            "blocks": blocks,
            "block_signups": block_signups,
            "show_eighth_profile_link": True,
        }

        return render(request, "eighth/multi_signup.html", context)


@login_required
@deny_restricted
def subscribe_to_club(request, activity_id):
    activity = get_object_or_404(EighthActivity, id=activity_id)

    if not activity.is_subscribable_for_user(request.user):
        messages.error(request, "You are not allowed to subscribe to this activity.")
        return http.HttpResponse(status=403)
    elif not activity.subscriptions_enabled:
        messages.error(request, "Subscriptions are not enabled for this activity.")
        return http.HttpResponse(status=403)

    activity.subscribers.add(request.user)

    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@deny_restricted
def unsubscribe_from_club(request, activity_id):
    activity = get_object_or_404(EighthActivity, id=activity_id)

    if activity.sponsors.filter(user=request.user).exists() or request.user in activity.club_sponsors.all():
        messages.error(request, "You cannot unsubscribe from an activity you sponsor.")
        return redirect("club_announcements")

    if request.user in activity.subscribers.all():
        activity.subscribers.remove(request.user)

    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@deny_restricted
def toggle_favorite_view(request):
    if request.method != "POST":
        return http.HttpResponseNotAllowed(["POST"], "HTTP 405: METHOD NOT ALLOWED")
    if not ("aid" in request.POST and is_entirely_digit(request.POST["aid"])):
        return http.HttpResponseBadRequest("Must specify an integer aid")

    aid = request.POST["aid"]
    with transaction.atomic():
        activity = get_object_or_404(EighthActivity, id=aid)
        # Lock on the User to prevent duplicates.
        lock_on([request.user])
        if activity.favorites.filter(id=request.user.id).nocache().exists():
            activity.favorites.remove(request.user)
            return http.HttpResponse("Unfavorited activity.")
        else:
            activity.favorites.add(request.user)
            return http.HttpResponse("Favorited activity.")


@login_required
def eighth_location(request):
    blocks = EighthBlock.objects.get_blocks_today()
    if blocks:
        sch_acts = []
        for b in blocks:
            try:
                act = request.user.eighthscheduledactivity_set.get(block=b)
                if act.activity.name != "z - Hybrid Sticky":
                    sch_acts.append([b, act, ", ".join([r.name for r in act.get_true_rooms()]), ", ".join([s.name for s in act.get_true_sponsors()])])
            except EighthScheduledActivity.DoesNotExist:
                sch_acts.append([b, None])

        response = render(request, "eighth/location.html", context={"sch_acts": sch_acts})
    else:
        messages.error(request, "There are no eighth period blocks scheduled today.")
        response = redirect("index")

    response.set_cookie("seen_eighth_location", "1", max_age=3 * 60 * 60)
    return response


@require_POST
@login_required
@deny_restricted
def leave_waitlist_view(request):
    if not settings.ENABLE_WAITLIST:
        return http.HttpResponseForbidden("Waitlist functionality is currently disabled.")

    for field in ("uid", "bid"):
        if not (field in request.POST and is_entirely_digit(request.POST[field])):
            return http.HttpResponseBadRequest(field + " must be an integer")

    uid = request.POST["uid"]
    bid = request.POST["bid"]

    try:
        user = get_user_model().objects.get(id=uid)
    except get_user_model().DoesNotExist:
        return http.HttpResponseNotFound("Given user does not exist.")
    EighthWaitlist.objects.filter(user_id=user.id, block_id=bid).delete()
    return http.HttpResponse("Successfully left waitlist for this activity.")


@login_required
@deny_restricted
def seen_new_feature_view(request):
    request.session["seen_feature"] = True
    return http.HttpResponse("Saved to session.")


@eighth_admin_required
@deny_restricted
def toggle_waitlist_view(request):
    if not settings.ENABLE_WAITLIST:
        return http.HttpResponseForbidden("Waitlist functionality is currently disabled.")

    request.session["disable_waitlist_transactions"] = not request.session.get("disable_waitlist_transactions", False)
    return http.HttpResponse("Successfully toggled waitlist transactions")
