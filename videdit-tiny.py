#!/usr/bin/python3

import os
import sys
import time
import subprocess
import argparse
import datetime

ffmpeg_bin = "/usr/bin/ffmpeg"
ffprobe_bin = "/usr/bin/ffprobe"
exiftool_bin = "/usr/bin/exiftool"
image_viewer = "/usr/bin/eog"
ffmpeg_quiet = ["-hide_banner", "-loglevel", "panic"]
ffmpeg_default_opts = ffmpeg_quiet + ["-c:a", "aac", "-crf", "19"]
ffmpeg_quick_opts = ffmpeg_quiet + ["-c:a", "aac", "-b:a", "96k",
                                    "-movflags", "+faststart", "-crf", "30"]
timeshift = "02:00"

__author__ = "Henning Hollermann"
__email__ = "laclaro@mail.com"
__version__ = "04/2020"
__license__ = "http://creativecommons.org/licenses/by-nc-sa/3.0/"
__usage__ = "{0} is a script to faciliate certain frequently ocurring video editing \
and conversion tasks. Use --help for more info.".format(os.path.basename(sys.argv[0]))

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--inputfile", required=True, action='append', 
                        help="Add input video file")
parser.add_argument("--quick", default=False, action='store_true', 
                        help="Quick mode: copy audio, use fast compression")
parser.add_argument("--dry", default=False, action='store_true', 
                        help="Do not execute commands, print only.")
parser.add_argument("--no_suggest", default=False, action='store_true',
                        help="Do not suggest filenames based on exif-data of related "
                             "image files.")
parser.add_argument("--show_image", default=False, action='store_true',
                        help="Use the configured image viewer to display the image "
                             "which matches best the exif date of the video.")
parser.add_argument("-f","--force", default=False, action='store_true', 
                        help="Force. Overwrite existing files.")
parser.add_argument("-v", "--version", action='store_true', help="Print version")

actionsgroup = parser.add_argument_group('ACTIONS')
actionsgroup.add_argument("--cut", action="store_true", help="Cut video")
actionsgroup.add_argument("--fade", default=True, action="store_true", 
                            help="Fade in video and fade out video. Default: 0.4 s")
actionsgroup.add_argument("--scale", action="store_true", 
                            help="Change video resolution encoding as mp4")
actionsgroup.add_argument("--transpose", choices=["CCWFlip", "90", "-90", "180", "CWFlip"],
                            help="Transpose or rotate video")
actionsgroup.add_argument("--mp4", action="store_true", 
                            help="Only encode input video files as mp4. This overrides " 
                            "cut, scale, fade and transpose.")
actionsgroup.add_argument("--rename", default=False, action='store_true', 
                        help="Rename output video based on image file from given imagedir "
                        "with the closest timestamp")

renamegroup = parser.add_argument_group('Arguments to --rename')
renamegroup.add_argument("-d","--dir", default="./", 
                        help="Directory with image files to guess the file name "
                        "for the video from the exif metadata.")
renamegroup.add_argument("-t","--tolerance", default="300", 
                        help="Time window in which an image file is treated as related "
                        "to the given video file.")

scalegroup = parser.add_argument_group('Arguments to --scale')
scalegroup.add_argument("-s", action='append', choices=["66","50","33", "720", "540", "320"], 
                            help="Add output video resolution. Default: 66%% (720p for HD input video)")

fadegroup = parser.add_argument_group('Arguments to --fade')
fadegroup.add_argument("-tf","--fadetime", default="0.3", 
                            help="Time to fadein and fadeout video. Default: 0.3 sec")
fadegroup.add_argument("-tb","--fadeblack", default="0.1", 
                            help="Time to delay fade, creating black time at "
                            "the beginning and the end of the video. Default: 0.1 sec")

cutgroup = parser.add_argument_group('Arguments to --cut')
cutgroup.add_argument("-ss", default="00:00:00", help="Starting time in seconds or in "
                            "format hh:mm:ss to cut from. Default: video beginning")
cutgroup.add_argument("-to", default="end", help="End time in format hh:mm:ss to cut to.")


def convert(source,target,arguments):
    """
    Convert video file based on the options passed to the script. In dry-mode
    this function only prints the ffmpeg command.
    """
    if args.quick:
        ffmpeg_arguments = arguments + ffmpeg_quick_opts
    else:
        ffmpeg_arguments = arguments + ffmpeg_default_opts

    if args.dry:
        print(ffmpeg_bin,'-i', source, *ffmpeg_arguments, target)
    else:
        print("Converting {} -> {}".format(source,target))
        try:
            subprocess.check_call([ffmpeg_bin,'-i', source, *ffmpeg_arguments, target])
        except subprocess.CalledProcessError:
            print("Aborted.")
            return
    copy_timstamps(source,target)


def copy_timstamps(sourcefile,targetfile):
    """
    This function uses exiftool and the datetimeoriginal of the source file to set the 
    modification time and the exif datetimeoriginal of the target file
    """
    exclude_tags=["--ImageSize", "--ImageWidth", "--ImageHeight"]
    if args.dry:
        print(" ".join([exiftool_bin, '-ee', '-overwrite_original', '-tagsFromFile',
                           sourcefile, *exclude_tags, targetfile]))
        print(" ".join([exiftool_bin, '-overwrite_original',
                           "-DateTimeOriginal<${datetimeoriginal}+" + timeshift,
                           targetfile]))
    else:
        success = False
        while not success:
            try:
                subprocess.check_call([exiftool_bin, '-ee', '-overwrite_original', '-tagsFromFile', 
                                      sourcefile, *exclude_tags, targetfile])
                subprocess.check_call([exiftool_bin, '-overwrite_original',
                                      "-DateTimeOriginal<${datetimeoriginal}+" + timeshift,
                                      targetfile])
                timestamp = subprocess.check_output("{0} -DateTimeOriginal -S -s "
                                                    "-d \'%Y-%m-%d %H:%M:%S%z\' "
                                                    "{1}".format(exiftool_bin, sourcefile),
                                                    shell=True)
                subprocess.check_call(['touch', '-d', timestamp, targetfile])
                success = True
            except:
                success = False


def get_small_edge(file):
    """Use ffprobe to determine the length video's short edge"""
    vidsize = subprocess.check_output("{0} -v error -select_streams v:0 "
                                      "-show_entries stream=width,height "
                                      "-of csv=s=x:p=0 {1}".format(ffprobe_bin, file),
                shell=True)
    size = vidsize.decode("utf-8").split("\n")[0].split("x")
    l = [int(i) for i in size]
    return min(l)

def get_duration(file):
    """Use ffprobe to determine the duration of a video file"""
    duration = subprocess.check_output("{0} -v error -show_entries format=duration "
                                       "-of default=noprint_wrappers=1:nokey=1 "
                                       "{1}".format(ffprobe_bin, file),
                                       shell=True)
    return duration

def get_timestr(seconds):
    """Construct dd days, hh:mm:ss string from seconds."""
    return str(datetime.timedelta(seconds=seconds)).rstrip("0")

def get_sec(time_str):
    """Get seconds from time string hh:mm:ss"""
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

def check_inputfile_exists():
    """Check if all input files exist, returns True on success"""
    all_exist = True
    for file in args.inputfile:
        if not os.path.isfile(file):
            print("No such file '{}'".format(file), file=sys.stderr)
            all_exist = False
    return all_exist

def get_closest_filepath(file,tolerance=300):
    """
    Uses exiftool to find the file with the closest exif timestamp compared to the input video file
    """
    vid_timestamp_str = subprocess.check_output("{0} -datetimeoriginal -CreationDateValue -FileModifyDate "
                                                "-S -s -d %s -T {1}".format(exiftool_bin, file),
                                                shell=True).decode("utf-8").split("\n")[0].split("\t")
    if all(e == "-" for e in vid_timestamp_str):
        print("Error: neither DateTimeOriginal nor CreationDateValue or FileModifyDate was found for file {}. "
              "Exiting".format(file))
        sys.exit()
    
    datetimeoriginal = vid_timestamp_str[0]
    creationdatevalue = vid_timestamp_str[1]
    filemodifydate = vid_timestamp_str[2]

    # if datetimeoriginal does not exists but creationdatevalue exists, copy value to datetimeoriginal
    if datetimeoriginal == "-" and creationdatevalue != "-":
        output = subprocess.check_output("{0} -if '!$DateTimeOriginal and $CreationDateValue' "
                                         "'-DateTimeOriginal<CreationDateValue' -overwrite_original "
                                         "{1}".format(exiftool_bin, file), shell=True).decode("utf-8").split("\n")[0].split("\t")
    vid_timestamp_str = subprocess.check_output("{0} -datetimeoriginal -CreationDateValue -FileModifyDate "
                                                "-S -s -d %s -T {1}".format(exiftool_bin, file),
                                                shell=True).decode("utf-8").split("\n")[0].split("\t")
    try:
        vid_timestamp = int(vid_timestamp_str[0])
    except ValueError:
        try:
            vid_timestamp = int(vid_timestamp_str[2])
            print("Info: using creation date value as indicator for " 
            "file {} due to a nonexistent DateTimeOriginal exif field.".format(file))
        except ValueError:
            print("Error: neither DateTimeOriginal nor FileModifyDate was found for file {}. "
                  "Exiting".format(file))
            sys.exit()
    try:
        exif_data_table = subprocess.check_output("{0} -filepath -datetimeoriginal -CreationDateValue -FileModifyDate " 
                        "-S -s -r -d %s -T -if \'$mimetype =~ m\"^image/[^x]\"\' "
                                                  "{1}".format(exiftool_bin, args.dir),
                                                  shell=True).decode("utf-8").split("\n")
    except subprocess.CalledProcessError:
        print("Warning: no images found in directory {0}. "
              "Disabling filename suggestion.".format(args.dir))
        args.no_suggest = True
        return None
    image_table = [item.split("\t") for item in exif_data_table if item]
    files = []
    times = []
    for item in image_table:
        try:
            times.append(int(item[1]))
        except:
            print("Warning: {} skipped.".format(file))
            continue
        files.append(item[0])

    vid_duration = float(get_duration(file))
    time_diff = []
    for time in times:
        if time-vid_timestamp >= 0:
            # if the image is taken after the video, the closest time is the exif date difference
            time_diff.append(abs(time - vid_timestamp))
        else:
            # if the image is taken prior to the video, the video duration is substracted
            # because its timestamp is written only at the end of capture
            time_diff.append(abs(time - vid_timestamp - vid_duration))
    min_time_diff = min(time_diff)
    image_closest_time = time_diff.index(min_time_diff)
    if min_time_diff > tolerance:
        print("Warning: No related file found for file {}. The one with the closest timestamp "
        "(difference {}, {}s) was {}".format(file,get_timestr(min_time_diff), int(min_time_diff),
                                        files[image_closest_time]))
        return None
    else:
        print("Info: file with {0} sec time difference found: "
              "{1}".format(min_time_diff, files[image_closest_time]))
        if args.show_image:
            subprocess.call([image_viewer, files[image_closest_time]])
        return files[image_closest_time]


def scale():
    """construct multiple scale filter:v according to -s scale arguments"""
    scale_filter={"66": "scale=iw/3*2:ih/3*2",
                  "50": "scale=iw/2:ih/2",
                  "33": "scale=iw/3:ih/3",
                  "720": "scale=iw/3*2:ih/3*2",
                  "540": "scale=iw/2:ih/2",
                  "320": "scale=iw/3:ih/3"}
    if not args.s:
        print("Warning: --scale without resolution given. Use 66%.")
        args.s = ["720"]
    if any(s in ["720", "540", "320"] for s in args.s):
        print("An absolute resolution was given. This script will interpret it as <given res.>/1080.") 
    # drop duplicate resolutions
    args.s = list(set(args.s))
    # return subset of scale_filter dictionary
    return {r: scale_filter[r] for r in args.s}


def transpose():
    """Construct transpose filter"""
    transpose={"CCWFlip":"transpose=0",
               "90":"transpose=1",
               "-90":"transpose=2",
               "180":"transpose=2,transpose=2",
               "CWFlip":"transpose=3"}
    return transpose[args.transpose]


def cut():
    """Return cut video arguments"""
    if not ':' in args.ss:
        args.ss = get_timestr(float(args.ss))
    elif not ':' in args.to:
        args.to = get_timestr(float(args.to))
    if not args.to:
        arg.to="end"
    return ["-ss", args.ss, "-to", args.to]


def fade(file):
    """Construct fade filter filter:v and filter:a"""
    d_in = d_out = round(float(args.fadetime), 2)
    black = round(float(args.fadeblack), 2)
    if args.cut:
        st_in=black + get_sec(args.ss)
        st_out=round(get_sec(args.to) - d_out - black, 2)
    else:
        try:
            duration = get_duration(file)
            st_in=0
            st_out=round(float(duration) - d_out, 2)
        except ValueError:
            return ["", ""]

    fade_filter_a = "afade=in:st={0}:d={1}," \
                    "afade=out:st={2}:d={3}".format(st_in, d_in, st_out, d_out)
    fade_filter_v = "fade=in:st={0}:d={1}," \
                    "fade=out:st={2}:d={3}".format(st_in, d_in, st_out, d_out)
    return [fade_filter_v,fade_filter_a]


def main():
    ffmpeg_args = ['-map_metadata', '0', '-movflags', 'use_metadata_tags']
    ffmpeg_filter_v = {}
    ffmpeg_filter_a = []
    cutopts=""
    transpose_filter=""
    outid = ""
    scale_filter={"100":""}

    if args.cut:
        cutopts = cut()
        outid = outid + "_cut"
        ffmpeg_args.extend(cutopts)

    if args.scale:
        filter_v = True
        scale_filter = scale()
    
    if args.transpose:
        filter_v = True
        outid = outid + "_" + args.transpose
        transpose_filter = transpose()

    if args.quick:
        outid = outid + "_quick"

    if args.fade:
        filter_v = True
        filter_a = True
    
    # for rotate and scale we compose a filter:v string 
    if filter_v:
        if args.scale:
            res_list = args.s
        else:
            # res_list 100 means: "do not scale at all" (returns empty filter)
            res_list = ["100"]
        for r in res_list:
            ffmpeg_filter_v[r] = ['-filter:v', ','.join([transpose_filter,
                                                         scale_filter[r]]).strip(",")]

    for file in args.inputfile:
        # use exiftool to get the file with the closest timestamp
        if not args.no_suggest:
            suggested = get_closest_filepath(file,int(args.tolerance))
        else:
            suggested = None
        if suggested and not args.no_suggest:
            prepend = os.path.splitext(suggested)[0] + '_'
        else:
            prepend = ""
        # if mp4 is specified, do nothing else
        if args.mp4:
            outfile = os.path.splitext(file)[0] + outid + '.mp4'
            if args.rename:
                outfile = prepend + os.path.basename(outfile)
            elif suggested and not args.no_suggest:
                print("Tip: You could rename the file manually to {0}{1} "
                      "or set the --rename flag.".format(prepend,
                                                         os.path.basename(outfile)))
            convert(file,outfile,ffmpeg_args)
        else:
            # process cut options
            # if args.to was not given, set it to the end of the file
            if args.cut and args.to == "end":
                args.to = get_timestr(float(get_duration(file)))
                ffmpeg_args[-1] = args.to
            if filter_v:
                # construct the fade video and audio filters
                fade_filter_v,fade_filter_a = fade(file)
                if args.fade:
                    ffmpeg_filter_a = ['-filter:a',fade_filter_a]
                # scaling filters and output file names are adjusted for every chosen resolution
                for r in ffmpeg_filter_v.keys():
                    outfile = file + outid + "_" + r + '.mp4'
                    if args.rename:
                        outfile = prepend + os.path.basename(outfile)
                    elif suggested and not args.no_suggest:
                        print("Tip: You could rename the file manually to {0}{1} "
                              "or set the --rename flag.".format(prepend,
                                                                 os.path.basename(outfile)))
                    if args.fade:
                        ffmpeg_filter_v[r][1] = ",".join([ffmpeg_filter_v[r][1],
                                                          fade_filter_v]).strip(",")
                    
                    # run ffmpeg (only prints command in DRY mode)
                    convert(file, outfile, ffmpeg_args + ffmpeg_filter_v[r] + ffmpeg_filter_a)
                


if __name__ == '__main__':

    # if no argument given, display usage and exit
    if len(sys.argv) == 1:
        print(__usage__)
        sys.exit()

    # process command line arguments
    args = parser.parse_args()
    
    # exit if an input file does not exist
    if not check_inputfile_exists():
        sys.exit()
    
    # run the script
    if args.dry:
        print("Running in DRY mode, so not changing any files.")
    main()
