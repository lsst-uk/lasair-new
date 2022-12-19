from django.contrib.auth import logout as auth_logout
from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import UserRegisterForm, ProfileUpdateForm, UserUpdateForm
from django.contrib.auth.decorators import login_required
import sys


def register(request):
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Your account has been created. Please now login.')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


@login_required
def profile(request):
    if request.method == "POST":
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)
        if u_form.is_valid() and p_form.is_valid():
            image = p_form.cleaned_data.get('image')
            u_form.save()
            p_form.save()
            messages.success(request, f'Your account has been updated.')
            return redirect('profile')
    else:
        # GET REQUEST
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'u_form': u_form,
        'p_form': p_form
    }
    return render(request, "users/profile.html", context)


@login_required(redirect_field_name=None)
def logout(request):
    # message user or whatever
    template_name = "users/logout.html"
    context = {
        'username': request.user.username,
        'profile_image': request.user.profile.image_b64
    }
    auth_logout(request)
    return render(request, "users/logout.html", context)
    # return logout(request)
