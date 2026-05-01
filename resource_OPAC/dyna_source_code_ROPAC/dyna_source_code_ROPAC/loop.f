      subroutine loop(starttime,endtime,maxintervals)
c --
c -- This is the main time loop for DYNASMART. It loops for every simulation
c -- interval.
c --
c -- This subroutine is called from the main (in the off-line case) or
c -- from CORBA (in the real-time case)
c --
c -- This subroutine calls the following subroutines.
c -- 1. gui_stat
c -- 2. display_results (this is a C code to activate the graphics)
c --	3. read_signals
c --	4. penalty_calculation
c --	5. ksp_main
c -- 	6. inci_check
c --    7. intersection_control
c --    8. get_link_capacity
c --    9. ksp_update
c --   10. demand_generation
c -    11. vehicle_simulation
c --   12. vms_main
c --   13. ramp_metering
c --   14. final_statistics
c --   15. link_pricing 
c --   
c -- INPUT :
c -- starttime : the staring simulation interval for the loop.
c -- endtime : the ending simulation interval for the loop.
c --
c -- OUTPUT :
c -- fort.4 which includes the following statistics
c -- l : the current simulation interval number.
c -- jj : total number of vehicels loaded till now.
c -- numcars : number of targe vehicles (between STATTM and ENDTM) still in the network.
c -- nout_nontag : number of non-tagged vehicles which reached their i
c --               destination.
c -- nout_tag : number of tagged vehicles which reached their destination.
c --
c -- fort.666 : moved to fort.6 after the end of the simulation.
c --            It outputs statistics about the vehicle generation process 
c --            and the termination reason.
c --
      use muc_mod
c	use vector_mod	!Alex: Temporal, it's not necessary to have vector_mod here . . .
      integer starttime,endtime,maxintervals,soindex
      integer load_veh,dy_muc,genelink,l
      real tiempo
      Logical LPFileExists	
      	dy_muc=0
c --
      do 12 l=starttime,endtime
c -- 
c -- t_start : the start of the current simulation interval (in seconds)
c -- time_now : the end of the current simulation interval (in seconds)
c --
      t_start=(l-1)*tii
      time_now=time_now+tii*60
c --
c -- int_d : display interval (input from the GUI).  It is the number of
c --         simulation intervals for each GUI referesh.
c --
c -- ireal : a flag received from the GUI to indicate the execution mode.
c --        If ireal =0, run off-line , if ireal=1 run real-time
c --
      if(mod((l-1),int_d).eq.0.and.l.gt.1)then
       call gui_stat(l)
      endif
c -- 
c -- update the signal timing plan counter
c --
      if(isig.gt.1)then
	 do mg=2,isig
	   !if((l*tii-strtsig(mg)).lt.0.1) then
	    if((l*tii-strtsig(mg)).gt.0.1)then
	    isigcount=isigcount+1
c --
	     !*******************
		 if(isigcount.gt.isig)then
			isigcount=isig
		 endif
		 !*********************	   
		 exit
	   endif
	 enddo
      endif
c --
c -- check if the start of a new signal timing plan has been reached.  If yes
c -- read the new signals and update the penalties and the shortest path.
c --
c	print *, 'Alex1'
c --
        !if(isig.gt.1.and.((l-1)*tii.eq.strtsig(isigcount))) then
	!*************************************
      if((isig.gt.1).and.(isigcount.gt.1))then
	if((l-1)*tii.gt.(strtsig(isigcount)-0.01).and.
     +  ((l-1)*tii.lt.(strtsig(isigcount)+0.01)))then
	   SignCount=0
      !*******************************************************
c --
           call read_signals()
           if(iteration.eq.0)then       
             call penalty_calculation(l)
             call link_pricing
             call kspcost_main(dy_muc)
           endif
        endif
	endif
c	print *, 'Alex2'
c --
c -- If there are some incidents in the network, call the inci_check
c --
       if(inci_num.gt.0) call inci_check(l*tii) 
c --
c	print *, 'Alex3'
c --
c -- If there are some work zones in the network, call the wz_check
c --
       if(WorkZoneNum.gt.0) call wz_check(l*tii) 
C --
c	if (l*tii.gt.2.7)
c	print *, 'Alex4'
c --
c -- for the first simulation interval, calculate the penalty
c --
      if(l.eq.1)then
        call penalty_calculation(l)
      endif
c	print *, 'Alex5'
c --
      call intersection_control(l)
c	print *, 'Alex6'
c --
      call get_link_capacity()
c --
c -- path calculation  
c -- kspstep : number of simulation intervals for K-shortest path calculation.
c -- kupstep : number of simulation intervals for K-shortest path update.
c --
c --
c	if (l*tii.gt.2.7)
c	print *, 'Alex7'
c --
c -- shortest path calculation or update   
c --
!      if(iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1.or.
!     *classpro(4)-classpro(3).gt.0.001.or.vms_num.gt.0)) then
      if((iteration.eq.0.and.(realdm.ne.2.or.noofstops.gt.1))
     *	.or.ienroute_ok.eq.1.or.vms_num.gt.0)then
c --
         if(mod(l,kspstep).eq.0.)then
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex71',VhcAtt_Value(42,12,1)
           call link_pricing
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex72',VhcAtt_Value(42,12,1)
c	tiempo=l*tii
           call kspcost_main(dy_muc)
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex73',VhcAtt_Value(42,12,1)
         else if(mod(L,kupstep).eq.0)then
           do itmp=1,noof_master_destinations
             if(destination(itmp).ne.0)then
               do ltype=1,no_link_type
                 do ioccup=1,no_occupancy_level
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex74',VhcAtt_Value(42,12,1)
                  call link_pricing
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex75',VhcAtt_Value(42,12,1)
                  call kspcost_update(itmp)
c	if (l*tii.gt.2.7)
c     +	print *, 'Alex76',VhcAtt_Value(42,12,1)
                 enddo
               enddo
	       endif
           enddo
         endif
      endif
c --
c	if (l*tii.gt.2.7)
c	print *, 'Alex8'
c --
c -- vehicle generation process : via OD matrix or path and vehicle files.
c --
c -- jtotal : total number of vehicles in the path and vehicle files.
c -- jrestore : number of vehicles already loaded + 1.
c -- 
      vlg(:)=0.0
      if(realdm.eq.1.and.iteration.eq.0)then
        call demand_generation(l)
      elseif(realdm.ne.1.and.iteration.eq.0)then
!	  vlg(:)=0
	  call read_vehicles(t_start)
	elseif(iteration.gt.0)then
!	  vlg(:)=0
	  load_veh=0
        do ji=jrestore,jtotal
c --
	if(ji.eq.117)then
	iiidebug =1 
	endif
          if(abs(stime(ji)-t_start).gt.0.01) goto 1920
c --
		jj_MUC=jj_MUC+1
           if(ioc(ji).eq.1)then
	          if(vehclass(ji).eq.3)then
                call get_genelink_from_uepath_lov(ji,genelink) 
	          elseif(vehclass(ji).eq.2)then
!	             call get_sopath_lov(ji,i,icurrnt(ji))
                call get_genelink_from_sopath_lov(ji,genelink) 
	          endif
           else
	          if(vehclass(ji).eq.3)then
!                 call get_uepath_hov(ji,i,icurrnt(ji))
                call get_genelink_from_uepath_hov(ji,genelink) 
	          elseif(vehclass(ji).eq.2)then
!	             call get_sopath_hov(ji,i,icurrnt(ji))
                call get_genelink_from_sopath_hov(ji,genelink) 
	          endif
           endif
c --
!          vlg(isec(ji))=vlg(isec(ji))+1
c --
		if(vehclass(ji).eq.2.or.vehclass(ji).eq.3)then ! We change generation links for SO or UE vehicles
			if(isec(ji).ne.genelink)then
			iiidebug=1
			endif
			isec(ji)=genelink
	    	endif
			vlg(isec(ji))=vlg(isec(ji))+1
			vlg_vhcID(isec(ji),vlg(isec(ji)))=ji
c --
          icurrnt(ji)=1
          if(stime(ji).ge.starttm.and.stime(ji).lt.endtm)then
            itag(ji)=1
            load_veh=load_veh+1
	    else 
	      itag(ji)=0
	    endif
        enddo
1920    jrestore=ji
        numcars=numcars+load_veh 
      endif
c	print *, 'Alex9'
      if(l.eq.starttime)then
        if(itedex.gt.0.and.iteration.eq.0.and.
     +               (iso_ok.eq.1.or.iue_ok.eq.1))then
C	print *, 'Alex91'
          call allocate_muc
	  endif
	endif
c	print *, 'Alex92'
c --
c  -- output initial paths for muc every soint interval
      if(iteration.eq.0)then
c --
      if((iso_ok.eq.1.or.iue_ok.eq.1).and.
     +   (itedex.gt.0.and.iteration.eq.0))then
         if(mod((l-1),tad).eq.0)then
            soindex=nint(float(L)/tad)+1
	      if(soindex.le.soint)then
c	print *, 'Alex93',soindex
             call build_mucpath_lov(soindex) !build muc path set
c	print *, 'Alex93b'
c --
!  	       if(total_hov.gt.0.00001) then
  	       if(Veh_Type(3).gt.0.00001)then
c	print *, 'Alex94'
             call build_mucpath_hov(soindex) !build muc path set
c	print *, 'Alex94b'
               endif
	      endif
	   endif
       endif
      endif
c --

c --
c -- vms_main is a subroutine for vms operation
c -- vms_num : is the number of vms.
c --
      if(vms_num.gt.0) call vms_main(t_start)
c --
c	 print *, 'Alex10'
       call vehicle_simulation(l,t_start,endtime)
c	 print *, 'Alex11'
c --
c -- Output the following statistics         
c -- l : the current simulation interval number.
c -- jj : total umber of vehicels loaded till now.
c -- numcars : number of vehicles still in the network.
c -- nout_nontag : number of non-tagged vehicles which reached their i
c --               destination.
c -- nout_tag : number of tagged vehicles which reached their destination. 
c --
c --
c -- STOP conditions: 1) if there are no vehicles in the network
c --                  2) The end planning horizone
c --                  3) there are no vehicles exits the network in 5 min
c --
       if(numcars.eq.0.and.l.gt.tlatest_bus/tii
     *    .and.l.gt.(starttm/tii+10))then
c     *	 iread_veh_count.ge.MaxVehicles) then
      write(6,*) '**************************************************'
      write(6,*) 'The program reached the end of simulation because:'
      write(6,*) 'all target vehicles have reached their destinations'
      write(6,*) '**************************************************'
      write(666,*) '**************************************************'
      write(666,*) 'The program reached the end of simulation because:'
      write(666,*) 'all target vehicles have reached their destinations'
      write(666,*) '**************************************************'
       goto 433
       endif
c --
c -- if there are some so or ue vehicels, print out some files for their
c -- procedure(s).
c --
      if((iso_ok.eq.1.or.iue_ok.eq.1).and.itedex.gt.0)then
c	 print *, 'Alex11a'
	 	   call calavg(L)
c	 print *, 'Alex11b'
	endif
c	if(iteration.gt.0) 
c	print *, 'Alex12'
c --
c -- ramp_metering is a subroutine to calculate 
c -- on-ramp rate on ramps.
c --
c -- intime : the number of simulation intervals in 1 minute.
c --
       if(dec_num.gt.0)then
         intime=nint(1/tii) 
         if(mod(l,intime*nrate).eq.0.and.l.gt.5)then
           call ramp_metering(t_start)
         endif
       endif
c	if(iteration.gt.0) 
c	print *, 'Alex13'
c --
c -- count the simulation intervals in which there are no vehicles going
c -- out of the network.
c -- If ther are some vehicles out during the current simulation interval, then
c -- reinitialize the counter.
c --
      if(numcars.eq.oldnumcars) icount_stop=icount_stop+1
      if(numcars.ne.oldnumcars) icount_stop=0
      oldnumcars=numcars
c --
c -- STOP check : if there are no vehicles getting out of the network for
c -- 50 simulation intervals and the end of the demand generation time
c -- has been reached, then stop.
c --
      if(icount_stop.eq.100.and.t_start.ge.begint(nints+1))then
      write(6,*) '**************************************************'
      write(6,*) 'The program reached the end of simulation because:'
      write(6,*) 'there are no target vehicles getting out of network'
      write(6,*) 'for',100*tii, 'minutes' 
      write(6,*) '**************************************************'
      write(666,*) '**************************************************'
      write(666,*) 'The program reached the end of simulation because:'
      write(666,*) 'there are no target vehicles getting out of network'
      write(666,*) 'for',100*tii, 'minutes' 
      write(666,*) '**************************************************'
       goto 433
      endif
c --
c -- print out some loading information for every 50 simulation intervals.
c --
c -- jj_i : total number of vehicles generated in the netwrok since beginning of the simulation
c  --       till the end of the previous simulation interval.
c --
c -- all veriables with _i at the end are for the previous simulation interval.
c --
c	if(iteration.gt.0) 
c	print *, 'Alex14'
      if(mod(l,idemand_info).eq.0)then
! Modified by MTI team Jan 28 0.930.9
!	   num_gen=jj-jj_i
	  if(iteration.eq.0)then	
	   num_gen=jj-jj_i
	  else
	   num_gen=jj_MUC
	   jj_MUC=0
	  endif
         nout_nontag_i=nout_nontag-nout_nontag_i
         nout_tag_i=nout_tag-nout_tag_i
! Modified by MTI team Jan 28 0.930.9
	  if(iteration.eq.0)then
	if(mod(l,10).eq.0)then	
      write(6,3411) l*tii,jj,
     +               num_gen,nout_nontag_i,nout_tag_i,numcars
	endif
	write(666,3411) l*tii,jj,
     +               num_gen,nout_nontag_i,nout_tag_i,numcars
	  else
	if(mod(l,10).eq.0)then	
      write(6,3411) l*tii,jrestore-1,
     +               num_gen,nout_nontag_i,nout_tag_i,numcars
	endif
	write(666,3411) l*tii,jrestore-1,
     +               num_gen,nout_nontag_i,nout_tag_i,numcars
	  endif
c --
3411  format(' T: ',f5.1,' Tot Veh: ',I6,' Gen: ',i6
     +              ,' Out_n: ',I6,' Out_t:',I6,' In_v:',I6)
         jj_i=jj
         nout_nontag_i=nout_nontag
         nout_tag_i=nout_tag
      endif
C --
c	if(iteration.gt.0) 
c	print *, 'Alex15'
12    continue
c --
c -- In the real time case, the CORBA code calls this subroutine every display
c -- interval, therefore, the gui_stat has to be called at the end of the loop.
c --
c	print *, 'Alex17'
433   continue
C --
c	print *, 'Alex18'
      MaxIntervals=min(L,endtime)
	call gui_stat(l)
c	print *, 'Alex19'
      INQUIRE(FILE='LinkFlowPOutput.Txt',EXIST=LPFileExists)
	if(LPFileExists)then
      call PrintLinkProportions(starttime,endtime,0)
	endif
c	print *, 'Alex20'
      INQUIRE(FILE='LinkDensityPOutput.Txt',EXIST=LPFileExists)
	if(LPFileExists)then
c	print *, 'Alex21'
      call PrintLinkProportions(starttime,endtime,1)
	endif
c --
c --  return
      return
      end
