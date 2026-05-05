      Subroutine flow_model_update

! =========================================================  
! --  $$$  Last update                                   ==
! --  Dates:   July 31                                   ==
! --  Authors: Yi-Chang Chiu                             == 
! --  Tasks:   Add Modified Greenshield data structure   ==
! --  Apply different Modified Greenshield  to different links                        ==
! =========================================================
        use muc_mod
      	real tlength
      	integer IQ

      	do 40 i=1,noofarcs
        ctmp(i)=0.0
        vtmp(i)=0.0
        c(i)=(partotal(i))/xl(i)
! --
! -- tlength is the queue-free lane length of the link.
! --
        tlength=xl(i)-(vehicle_queue(i)*vehicle_length/(5280.0))
! --
        tlength=max(0.001,tlength)
        ctmp(i)=(volume(i)-vehicle_queue(i))/tlength
! -- 
! -- prepare for the concentration in two ways
! -- c(i) : the one will be used in the simulation
! -- ctmp(i) : for short term prediction
! --
        c(i)=min(c(i),cmax(i))
        ctmp(i)=min(ctmp(i),cmax(i))

! -- calculatc v the average speed

        IQ=FlowModelType(FlowModelnum(i))
        IH=FlowModelnum(i)
		 
! The speed updating mechanism is different for type 1 link and type 2

         if(c(i).le.MGreenS(IH)%KCut)then !free-flow regime
           v(i)=(SpeedLimit(i)+Vfadjust(i))/60.0
         elseif((c(i).gt.MGreenS(IH)%KCut).and.(c(i).le.
     +	     MGreenS(IH)%Kjam2))then ! Modified GreenShield Regime
	         if(IQ.eq.1)then ! with flat part
           v(i)=(MGreenS(IH)%Vf2+Vfadjust(i)-MGreenS(IH)%V02)/60.0*
     +          ((1-c(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2+
     +          MGreenS(IH)%V02/60.0
	        elseif(IQ.eq.2)then ! without flat part
        v(i)=(SpeedLimit(i)+Vfadjust(i)-MGreenS(IH)%V02)/60.0*
     +  ((1-c(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2+
     +	 MGreenS(IH)%V02/60.0
            else
              write(911,*) 'error in flow_model_update'
	        endif
        else ! minimal speed regime
           v(i)=MGreenS(IH)%V02/60.0
        endif
		
c        if(i.eq.35)then
c          print *,v(i),MGreenS(IH)%V02/60.0,
c     +  (SpeedLimit(i)+Vfadjust(i)-MGreenS(IH)%V02)/60.0*
c     +  ((1-c(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2+
c     +	 MGreenS(IH)%V02/60.0,
c     +   (MGreenS(IH)%Vf2+Vfadjust(i)-MGreenS(IH)%V02)/60.0*
c     +          ((1-c(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2+
c     +          MGreenS(IH)%V02/60.0	 
c        endif
		
! -- calculatc vtmp, the queue-free speed
        if(ctmp(i).le.MGreenS(IH)%KCut)then !free-flow regime
          vtmp(i)= (SpeedLimit(i)+Vfadjust(i))/60.0
        elseif((ctmp(i).gt.MGreenS(IH)%KCut).and.(ctmp(i).le.
     +  MGreenS(IH)%Kjam2))then ! Modified GreenShield Regime
	        if(IQ.eq.1)then ! with flat part
         vtmp(i)=(MGreenS(IH)%Vf2+Vfadjust(i)-MGreenS(IH)%V02)/
     +  60.0*((1-ctmp(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2+
     +  MGreenS(IH)%V02/60.0
	        elseif (IQ.eq.2)then ! without flat part
        vtmp(i)=(SpeedLimit(i)+Vfadjust(i)-MGreenS(IH)%V02)/
     +  60.0*((1-ctmp(i)/MGreenS(IH)%Kjam2))**MGreenS(IH)%alpha2
     +  +MGreenS(IH)%V02/60.0
            else
        write(911,*) 'error in flow_model_update'
	        endif
         else ! minimal speed regime
           vtmp(i)= MGreenS(IH)%V02/60.0
        endif
! --
! -- preapre the travel time along link to TTimeOfBackLink(link)
! --
       TTimeOfBackLink(ForToBackLink(i))=tlength/(nlanes(i)*vtmp(i))
       statmpt(i)=tlength/(nlanes(i)*vtmp(i))
		  
40    continue

      return
      end
